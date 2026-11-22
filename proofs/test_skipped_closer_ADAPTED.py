"""#5756: a tool-call value whose model skipped its own </parameter> (a nested <parameter=X</tool_call>...</parameter> pair in
the value made the parser end the value at the nested close, delivering a truncated parameter).
Parser-level and deterministic - no model, no GPU. The three first assertions are the issue's verbatim
reproduction, pinned at the `main` (dbb2d168) lineage, where they truncate to <parameter=limit>25.

    python -m unittest serve.test_skipped_closer
"""
import json
import unittest

from terminal.serve.frontend import OutputParser, param_end, parse_tool_call

S = {"type": "string"}


def tool(name, **props):
    return {"name": name, "parameters": {"type": "object", "properties": props}}


EDIT = tool("edit_file", path=S, old_string=S, new_string=S)
BASH = tool("bash", command=S)

# the three parser-level cases from issue #5756 and the value each one must keep
REPRO = [("<parameter=limit>25</parameter>\n</function>\n</tool_call>", "<parameter=limit>25</parameter>\n"),
         ("<parameter=limit>25</parameter>\n<parameter=old_string>x</parameter>\n</function>", "<parameter=limit>25</parameter>\n<parameter=old_string>x</parameter>\n"),
         ("<parameter=limit>25</parameter>\n</parameter>\n</function>", "<parameter=limit>25</parameter>\n")]


class ParserLevel(unittest.TestCase):
    def test_the_issue_three_cases(self):
        for t, want in REPRO:
            e = param_end(t, final=True, name="new_string")
            self.assertEqual(t[:e], want)

    def test_the_old_rule_stays_for_quoted_calls(self):
        # skipped=False is the reasoning's rule: the first close still ends the value (unchanged behavior)
        t, _ = REPRO[0]
        e = param_end(t, final=True, name="new_string", skipped=False)
        self.assertEqual(t[:e], "<parameter=limit>25")

    def test_no_schema_means_no_declared_rule(self):
        # the schemas=None route: the value may only end before </function> / </tool_call>, never before an unrelated opener
        t, want = REPRO[1]
        e = param_end(t, final=True, name="new_string", declared=None)
        self.assertEqual(t[:e], want)

    def test_declared_opener_ends_the_value(self):
        t = "<parameter=limit>25</parameter>\n<parameter=old_string>x</parameter>\n</function>"
        e = param_end(t, final=True, name="new_string", declared={"path", "old_string", "new_string"})
        self.assertEqual(t[:e], "<parameter=limit>25</parameter>\n")

    def test_streaming_holds_a_split_boundary_tag(self):
        # a closer or a boundary split across windows must never end the value early: -2, hold from the first close
        for cut in range(1, 24):
            t = REPRO[0][0][:cut]
            e = param_end(t, final=False, name="new_string")
            self.assertLessEqual(e, 0, f"released early at cut {cut}: {t[e:]!r}")
        e = param_end("<parameter=limit>25</parameter>\n~FU", final=False, name="new_string")
        self.assertEqual(e, -2)
        e = param_end("<parameter=limit>25</parameter>\n<parameter=o", final=False, name="new_string", declared={"old_string"})
        self.assertEqual(e, -2)


def parse_all(text, tools, **kw):
    p = OutputParser(thinking=False, tools=tools, recover=True, **kw)
    evs = p.feed(text) + p.finish("stop")
    return [(e.call.name, e.call.arguments) for e in evs if e.kind == "tool_call"]


class EndToEnd(unittest.TestCase):
    def test_skipped_closer_and_next_declared_parameter(self):
        text = ("<tool_call>\n<function=edit_file>\n<parameter=path>\ndocs/tools.md\n</parameter>\n<parameter=new_string>\n"
                "line one\n<parameter=limit>25</parameter>\nline three\n"
                "<parameter=old_string>old\n</parameter>\n</function>\n</tool_call>")
        self.assertEqual(parse_all(text, [EDIT]),
                         [("edit_file", {"path": "docs/tools.md",
                                         "new_string": "line one\n<parameter=limit>25</parameter>\nline three",
                                         "old_string": "old"})])

    def test_one_wrapper_two_calls_after_a_skipped_closer(self):
        text = ("<tool_call>\n<function=edit_file>\n<parameter=new_string>\n<parameter=limit>25</parameter>\n</function>\n"
                "<function=bash>\n<parameter=command>ls\n</parameter>\n</function>\n</tool_call>")
        self.assertEqual(parse_all(text, [EDIT, BASH]),
                         [("edit_file", {"new_string": "<parameter=limit>25</parameter>"}),
                          ("bash", {"command": "ls"})])

    def test_a_complete_nested_pair_still_closes_normally(self):
        text = ("<tool_call>\n<function=edit_file>\n<parameter=new_string>\n<parameter=limit>25</parameter>\ntext\n</parameter>\n</function>\n</tool_call>")
        self.assertEqual(parse_all(text, [EDIT]),
                         [("edit_file", {"new_string": "<parameter=limit>25</parameter>\ntext"})])

    def test_batch_route_without_a_schema(self):
        # parse_tool_call with schema=None: the declared-parameter rule is off, </function> still ends the value
        body = ("<function=edit_file>\n<parameter=new_string>\n<parameter=limit>25</parameter>\n<parameter=old_string>x</parameter>\n</function>")
        call = parse_tool_call(body, None)
        self.assertEqual(call.name, "edit_file")
        self.assertEqual(call.arguments["new_string"], "<parameter=limit>25</parameter>\n<parameter=old_string>x</parameter>")


class Streaming(unittest.TestCase):
    TWO_CALLS = ("<tool_call>\n<function=edit_file>\n<parameter=new_string>\n<parameter=limit>25</parameter>\n</function>\n"
                 "<function=bash>\n<parameter=command>ls\n</parameter>\n</function>\n</tool_call>")
    EXPECT = [{"new_string": "<parameter=limit>25</parameter>"}, {"command": "ls"}]

    def test_deltas_decode_to_the_final_call_at_every_split(self):
        # the issue's chunk sweep: every split point of every closer and boundary tag, 1..24 chars
        for size in range(1, 25):
            p = OutputParser(thinking=False, tools=[EDIT, BASH], stream_tools=True, recover=True)
            evs = []
            for i in range(0, len(self.TWO_CALLS), size):
                evs += p.feed(self.TWO_CALLS[i:i + size])
            evs += p.finish("stop")
            buckets, cur = [], None
            finals = []
            for e in evs:
                if e.kind == "tool_start":
                    cur = []
                    buckets.append(cur)
                elif e.kind == "tool_args":
                    cur.append(e.text)
                elif e.kind == "tool_call":
                    finals.append((e.call.name, e.call.arguments))
            self.assertEqual(finals, [("edit_file", self.EXPECT[0]), ("bash", self.EXPECT[1])], f"size {size}")
            for b, want in zip(buckets, self.EXPECT):
                got = "".join(b)
                self.assertEqual(got, json.dumps(want, separators=(",", ":")),
                                 f"size {size}: streamed {got!r} != final")


if __name__ == "__main__":
    unittest.main()