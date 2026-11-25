import sys, types, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for name in ("folder_paths", "server", "av"):
    sys.modules[name] = types.ModuleType(name)
sys.modules["server"].PromptServer = object
import importlib.util
spec = importlib.util.spec_from_file_location("h3chain_nodes", os.path.join(sys.path[0], "nodes.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

assert m.parse_cuts("12.5, 3,  , x, 30") == [3.0, 12.5, 30.0]
assert m.parse_scene_texts("a\nb\n\nc\n---\nd") == ["a b", "c", "d"]
assert m.parse_scene_texts("   ")[0].startswith("@Singer")
assert m.split_scenes(25, [], 10) == [[0.0, 10], [10, 20], [20, 25]]
assert m.split_scenes(22, [], 10) == [[0.0, 10], [10, 22]], m.split_scenes(22, [], 10)   # 2 s tail merged
assert m.split_scenes(30, [3, 12, 14, 25], 10) == [[0.0, 14], [14, 25], [25, 30]], m.split_scenes(30, [3, 12, 14, 25], 10)
assert m.split_scenes(8, [40], 0) == [[0.0, 8]]
d = json.loads(m.shots_document(9.417, "@Singer sings.", "ink", "lock"))
assert d["shots"][0]["end"] == 9.417 and d["audio"][0]["context_id"] == m.AUDIO_CTX and d["audio"][0]["mode"] == "lock"
# tail silence: own ending scene cut exactly at the song end, or (too short / no text) just a longer last scene
assert m.plan_spans(90.67, 95.67, [], 10, True) == ([[0.0, 10], [10, 20], [20, 30], [30, 40], [40, 50], [50, 60], [60, 70], [70, 80], [80, 90.67], [90.67, 95.67]], True)
assert m.plan_spans(90.67, 93.67, [], 10, True)[1] is False                    # 3 s is shorter than one H3 scene
assert m.plan_spans(90.67, 95.67, [], 10, False) == (m.split_scenes(95.67, [], 10), False)
assert m.plan_spans(30, 30, [], 10, True) == (m.split_scenes(30, [], 10), False)   # no silence
import numpy as np, tempfile
p = os.path.join(tempfile.mkdtemp(), "t.wav")
w = np.stack([np.linspace(-0.5, 0.5, 4410), np.zeros(4410)]).astype(np.float32)
m._write_wav(p, w, 44100); r, rate = m._read_wav(p)
assert rate == 44100 and r.shape == (2, 4410) and abs(r[0, -1] - 0.5) < 1e-3
print("all logic tests passed")
# dialogue: only the lines that start in the first render part reach the Director
sp = json.dumps([[{"text": "Hi!", "speaker_id": "ctx_a", "language": "English", "start": 0.6},
                  {"text": "Hello.", "speaker_id": "ctx_b", "language": "English", "start": 5.2}], []])
L = m.parse_spoken(sp)
assert [x["text"] for x in m.first_part_lines(L, 0, [121, 105])] == ["Hi!"]        # part 1 = 121 frames (5.04 s)
assert [x["text"] for x in m.first_part_lines(L, 0, [121])] == ["Hi!", "Hello."]     # one part: all lines
assert m.first_part_lines(L, 1, [121]) == [] and m.first_part_lines(L, 5, [121]) == [] and m.parse_spoken("") == []
assert "start" not in m.first_part_lines(L, 0, [121])[0]
d = json.loads(m.shots_document(9.4, "x", "", "lock", m.first_part_lines(L, 0, [121, 105])))
assert d["shots"][0]["spoken"][0]["speaker_id"] == "ctx_a"
print("dialogue tests passed")
