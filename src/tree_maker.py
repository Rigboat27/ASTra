import os
import json
from tree_sitter import Language, Parser
import tree_sitter_cpp as tscpp
import tree_sitter_python as tspy
import tree_sitter_java as tsjava

# ================= LANGUAGE DETECTOR =================

def detect_language(code: str):
    code_lower = code.lower()

    if "#include" in code:
        if "iostream" in code or "std::" in code:
            return "cpp"
        return "c"

    if "public static void main" in code_lower or "system.out.println" in code_lower:
        return "java"

    if "def " in code_lower or "import " in code_lower:
        return "python"

    return "unsupported"


# ================= CONFIG =================

CONFIG = {
    "python": {
        "lang": Language(tspy.language()),
        "loops": {"for_statement", "while_statement"},
        "conditions": {"if_statement"}
    },
    "cpp": {
        "lang": Language(tscpp.language()),
        "loops": {"for_statement", "while_statement", "do_statement", "ranged_for_statement"},
        "conditions": {"if_statement"}
    },
    "c": { 
        "lang": Language(tscpp.language()),
        "loops": {"for_statement", "while_statement", "do_statement"},
        "conditions": {"if_statement"}
    },
    "java": {
        "lang": Language(tsjava.language()),
        "loops": {"for_statement", "while_statement", "do_statement", "enhanced_for_statement"},
        "conditions": {"if_statement"}
    }
}



# ================= FEATURE EXTRACTOR (IR) =================

class FeatureExtractor:
    def __init__(self, loop_types, condition_types):
        self.loop_types = loop_types
        self.condition_types = condition_types

        self.max_loop_depth = 0
        self.current_depth = 0
        self.total_loops = 0
        self.conditions = 0
        self.function_calls = 0
        self.loop_types_used = set()

    def traverse(self, node):
        is_loop = node.type in self.loop_types
        is_condition = node.type in self.condition_types

        if is_loop:
            self.total_loops += 1
            self.current_depth += 1
            self.max_loop_depth = max(self.max_loop_depth, self.current_depth)
            self.loop_types_used.add(node.type)

        if is_condition:
            self.conditions += 1

        if node.type == "call_expression":
            self.function_calls += 1

        for child in node.children:
            if child.is_named:
                self.traverse(child)

        if is_loop:
            self.current_depth -= 1

    def build(self):
        return {
            "max_loop_depth": self.max_loop_depth,
            "total_loops": self.total_loops,
            "has_nested_loops": self.max_loop_depth > 1,
            "loop_types": list(self.loop_types_used),
            "conditions": self.conditions,
            "function_calls": self.function_calls
        }


# ================= DATA FLOW =================

class DataFlowAnalyzer:
    def __init__(self):
        self.variables = {}
        self.assignments = {}
        self.usages = {}
        self.constraints = []

    def record_variable(self, name, kind):
        if name not in self.variables:
            self.variables[name] = set()
        self.variables[name].add(kind)

    def record_assignment(self, name, line):
        if name not in self.assignments:
            self.assignments[name] = []
        self.assignments[name].append(line)

    def record_usage(self, name, line):
        if name not in self.usages:
            self.usages[name] = []
        self.usages[name].append(line)

    def add_constraint(self, constraint):
        self.constraints.append(constraint)

    def traverse(self, node, source_code):
        text = source_code[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")

        if node.type == "identifier":
            name = text.strip()
            self.record_variable(name, "used")
            self.record_usage(name, node.start_point[0])

        if node.type in ["assignment_expression", "init_declarator"]:
            for child in node.children:
                if child.type == "identifier":
                    name = source_code[child.start_byte:child.end_byte].decode("utf-8")
                    self.record_variable(name, "assigned")
                    self.record_assignment(name, node.start_point[0])

        if node.type == "if_statement":
            condition_text = text.split("{")[0]

            if "<" in condition_text:
                self.add_constraint(f"{condition_text.strip()} implies upper bound")
            elif ">" in condition_text:
                self.add_constraint(f"{condition_text.strip()} implies lower bound")
            elif "==" in condition_text:
                self.add_constraint(f"{condition_text.strip()} equality constraint")

        for child in node.children:
            if child.is_named:
                self.traverse(child, source_code)

    def build(self):
        return {
            "variables": {k: list(v) for k, v in self.variables.items()},
            "assignments": self.assignments,
            "usages": self.usages,
            "constraints": self.constraints[:10]
        }


# ================= AST GENERATOR =================

def generate_tree_json(node, source_code, loop_types, current_loop_depth=0):
    is_loop = node.type in loop_types

    if is_loop:
        current_loop_depth += 1

    node_text = source_code[node.start_byte:node.end_byte].decode("utf-8", errors="ignore").strip()
    first_line = node_text.split("\n")[0] if node_text else ""

    if len(first_line) > 80:
        first_line = first_line[:77] + "..."

    node_json = {
        "type": node.type,
        "snippet": first_line,
        "loop_depth": current_loop_depth if is_loop else 0,
        "children": []
    }

    for child in node.children:
        if child.is_named:
            node_json["children"].append(
                generate_tree_json(child, source_code, loop_types, current_loop_depth)
            )

    return node_json


# ================= CRITICAL SEGMENTS =================

def extract_critical_segments(node, source_code, segments):
    important_nodes = {
        "for_statement",
        "while_statement",
        "if_statement",
        "function_definition",
        "method_declaration"
    }

    if node.type in important_nodes:
        snippet = source_code[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        first_line = snippet.split("\n")[0]
        segments.append(first_line.strip())

    for child in node.children:
        if child.is_named:
            extract_critical_segments(child, source_code, segments)


# ================= MAIN PIPELINE =================

def analyze_code(code: str):
    language = detect_language(code)

    if language not in CONFIG:
        return json.dumps({"error": "Unsupported language"})

    config = CONFIG[language]

    parser = Parser(config["lang"])
    tree = parser.parse(bytes(code, "utf-8"))

    # -------- IR --------
    extractor = FeatureExtractor(config["loops"], config["conditions"])
    extractor.traverse(tree.root_node)
    ir = extractor.build()

    # -------- DATA FLOW --------
    dataflow = DataFlowAnalyzer()
    dataflow.traverse(tree.root_node, bytes(code, "utf-8"))
    dataflow_ir = dataflow.build()

    # -------- AST --------
    ast_json = generate_tree_json(tree.root_node, bytes(code, "utf-8"), config["loops"])

    # -------- CRITICAL SEGMENTS --------
    segments = []
    extract_critical_segments(tree.root_node, bytes(code, "utf-8"), segments)

    # -------- FINAL PAYLOAD --------
    payload = {
        "language": language,
        "ir": ir,
        "data_flow": dataflow_ir,
        "critical_code_segments": segments[:10],
        "ast": ast_json,
        "code": code[:2000]
    }

    return json.dumps(payload, indent=2, ensure_ascii=False)


# ================= RUN =================

if __name__ == "__main__":
    with open("code_cpp.cpp", "r", encoding="utf-8", errors="ignore") as f:
        code = f.read()

    result = analyze_code(code)
    print(result)