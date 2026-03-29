import json
import logging
import inspect
from typing import Any

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import AgentCard, TaskState, TextPart, UnsupportedOperationError
from a2a.utils.errors import ServerError
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class OpenAIAgentExecutor(AgentExecutor):
    def __init__(
        self,
        card: AgentCard,
        tools: dict[str, Any],
        api_key: str,
        system_prompt: str,
        base_url: str | None = None
    ):
        self._card = card
        self.tools = tools
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url
        )
        self.model = 'gpt-4o'
        self.system_prompt = system_prompt

    async def _process_request(self, message_text: str, context: RequestContext, task_updater: TaskUpdater) -> None:
        messages = [
            {'role': 'system', 'content': self.system_prompt},
            {'role': 'user', 'content': message_text},
        ]

        openai_tools = []
        for tool_name, tool_instance in self.tools.items():
            if hasattr(tool_instance, tool_name):
                func = getattr(tool_instance, tool_name)
                schema = self._extract_function_schema(func)
                openai_tools.append({'type': 'function', 'function': schema})

        max_iterations = 10
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=openai_tools if openai_tools else None,
                    tool_choice='auto' if openai_tools else None,
                    temperature=0.1,
                    max_tokens=4000,
                )

                message = response.choices[0].message
                messages.append({'role': 'assistant', 'content': message.content, 'tool_calls': message.tool_calls})

                if message.tool_calls:
                    for tool_call in message.tool_calls:
                        function_name = tool_call.function.name
                        function_args = json.loads(tool_call.function.arguments)

                        logger.debug(f'Calling tool: {function_name} with args: {function_args}')

                        if function_name in self.tools:
                            tool_instance = self.tools[function_name]
                            if hasattr(tool_instance, function_name):
                                method = getattr(tool_instance, function_name)
                                result = method(**function_args)
                                if inspect.iscoroutine(result):
                                    result = await result
                            else: result = {'error': f'Method not found'}
                        else: result = {'error': f'Function not found'}

                        if hasattr(result, 'model_dump'): result_json = json.dumps(result.model_dump())
                        elif isinstance(result, dict): result_json = json.dumps(result)
                        else: result_json = str(result)

                        messages.append({'role': 'tool', 'tool_call_id': tool_call.id, 'content': result_json})

                    await task_updater.update_status(
                        TaskState.working,
                        message=task_updater.new_agent_message([TextPart(text=f'Executing {function_name}...')])
                    )
                    continue

                if message.content:
                    parts = [TextPart(text=message.content)]
                    await task_updater.add_artifact(parts)
                    await task_updater.complete()
                break

            except Exception as e:
                logger.error(f'Error in API call: {e}')
                error_parts = [TextPart(text=f'{{"status": "error", "message": "{e!s}"}}')]
                await task_updater.add_artifact(error_parts)
                await task_updater.complete()
                break

        if iteration >= max_iterations:
            error_parts = [TextPart(text='{"status": "error", "message": "Max iterations reached."}')]
            await task_updater.add_artifact(error_parts)
            await task_updater.complete()

    def _extract_function_schema(self, func):
        sig = inspect.signature(func)
        docstring = inspect.getdoc(func) or ''
        description = docstring.split('\n')[0] if docstring else func.__name__
        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            param_type = 'string'
            if param.annotation != inspect.Parameter.empty:
                if param.annotation == int: param_type = 'integer'
                elif param.annotation == float: param_type = 'number'
                elif param.annotation == bool: param_type = 'boolean'
            if param.default == inspect.Parameter.empty: required.append(param_name)
            properties[param_name] = {'type': param_type, 'description': f'Parameter {param_name}'}

        return {'name': func.__name__, 'description': description, 'parameters': {'type': 'object', 'properties': properties, 'required': required}}

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        if not context.current_task: await updater.submit()
        await updater.start_work()

        message_text = ''.join(part.root.text for part in context.message.parts if isinstance(part.root, TextPart))
        await self._process_request(message_text, context, updater)

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        raise ServerError(error=UnsupportedOperationError())
