"""
확인용 웹 UI 서버. 추가 패키지 불필요 (stdlib only).
python demo.py 실행 후 http://localhost:8000 접속.
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from app.state import create_state, GLOBAL_DICT
from app.simulator import run_simulation

HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>ArchReactor Demo</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', sans-serif; background: #f5f5f5; color: #333; padding: 24px; }
  h1 { color: #333; margin-bottom: 16px; font-size: 22px; }
  .container { display: flex; gap: 20px; }
  .left { width: 320px; flex-shrink: 0; }
  textarea { width: 100%; height: 200px; background: #fff; color: #333; border: 1px solid #ddd;
             padding: 12px; font-family: 'Consolas', monospace; font-size: 14px; border-radius: 6px; resize: vertical; }
  button { margin-top: 10px; padding: 10px 24px; background: #4a90d9; color: #fff; border: none;
           border-radius: 6px; font-size: 15px; cursor: pointer; }
  button:hover { background: #3a7bc8; }
  .right { flex: 1; overflow-x: auto; display: flex; gap: 16px; }
  .visual { flex: 1; }
  .json-panel { width: 380px; flex-shrink: 0; }
  .json-panel pre { background: #1e1e1e; border: 1px solid #ddd; border-radius: 6px; padding: 14px;
                    font-size: 12px; color: #a8d8a8; font-family: 'Consolas', monospace;
                    overflow: auto; max-height: 80vh; white-space: pre-wrap; word-break: break-all; }
  .cycle-card { background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 14px; border: 1px solid #e0e0e0; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  .cycle-title { color: #4a90d9; font-weight: bold; font-size: 16px; margin-bottom: 10px; }
  .stages { display: flex; gap: 10px; flex-wrap: wrap; }
  .stage { background: #f0f4f8; border-radius: 6px; padding: 10px 14px; min-width: 180px; flex: 1; border: 1px solid #e0e0e0; }
  .stage-name { color: #4a90d9; font-weight: bold; font-size: 13px; margin-bottom: 6px; }
  .stage pre { font-size: 12px; color: #555; white-space: pre-wrap; word-break: break-all; }
  .regs { margin-top: 8px; font-size: 12px; color: #888; }
  .regs span { color: #4a90d9; }
  .summary { background: #fff; border: 1px solid #e0e0e0; border-radius: 6px; padding: 12px; margin-bottom: 14px; font-size: 14px; }
  .arrow { color: #999; font-size: 18px; margin: 0 2px; }
</style>
</head>
<body>
<h1>ArchReactor - Stage Viewer</h1>
<div class="container">
  <div class="left">
    <textarea id="code" spellcheck="false">addi x1, x0, 42
addi x2, x0, 10
add x3, x1, x2
sw x3, 0(x0)
lw x4, 0(x0)</textarea>
    <button onclick="run()">Run Simulation</button>
  </div>
  <div class="right">
    <div class="visual" id="output"></div>
    <div class="json-panel">
      <h3 style="color:#333; margin-bottom:8px; font-size:14px;">Raw JSON</h3>
      <pre id="jsonView">시뮬레이션을 실행하면 여기에 JSON이 표시됩니다.</pre>
    </div>
  </div>
</div>
<script>
async function run() {
  const code = document.getElementById('code').value.trim();
  const lines = code.split('\\n').filter(l => l.trim());
  const res = await fetch('/api/simulate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({instructions: lines})
  });
  const data = await res.json();
  const out = document.getElementById('output');
  let html = `<div class="summary">Status: ${data.status} &nbsp;|&nbsp; Cycles: ${data.summary.total_cycles} &nbsp;|&nbsp; Instructions: ${data.summary.instructions_executed}</div>`;

  for (const snap of data.history) {
    const s = snap.stages;
    html += `<div class="cycle-card">`;
    html += `<div class="cycle-title">Cycle ${snap.cycle} &nbsp; (PC: ${snap.stages.IF.pc})</div>`;
    html += `<div class="stages">`;

    const stageOrder = ['IF','ID','EX','MEM','WB'];
    for (let i = 0; i < stageOrder.length; i++) {
      const name = stageOrder[i];
      html += `<div class="stage"><div class="stage-name">${name}</div><pre>${formatStage(name, s[name])}</pre></div>`;
      if (i < stageOrder.length - 1) html += `<div class="arrow" style="align-self:center">→</div>`;
    }
    html += `</div>`;

    // 변경된 레지스터만 표시
    const regs = snap.registers;
    let regStr = '';
    for (let i = 1; i < 32; i++) {
      if (regs[i] !== 0) regStr += `<span>x${i}</span>=${regs[i]}  `;
    }
    if (regStr) html += `<div class="regs">Registers: ${regStr}</div>`;
    html += `</div>`;
  }
  out.innerHTML = html;
  // JSON 표시용: registers를 0이 아닌 것만 필터링
  const display = structuredClone(data);
  for (const snap of display.history) {
    const filtered = {};
    snap.registers.forEach((v, i) => { if (v !== 0) filtered[`x${i}`] = v; });
    snap.registers = filtered;
  }
  document.getElementById('jsonView').textContent = JSON.stringify(display, null, 2);
}

function formatStage(name, data) {
  if (name === 'IF') return `instr: ${data.instruction}`;
  if (name === 'ID') return `op: ${data.op}\\nrd: x${data.rd}\\nrs1: x${data.rs1.reg} (${data.rs1.value})\\nrs2: x${data.rs2.reg} (${data.rs2.value})\\nimm: ${data.imm}`;
  if (name === 'EX') return `${data.alu_op} ${data.operand1}, ${data.operand2}\\n= ${data.alu_result}`;
  if (name === 'MEM') {
    if (!data.accessed) return 'no access';
    if (data.operation === 'load') return `LOAD [${data.address}]\\n→ ${data.read_data}`;
    return `STORE [${data.address}]\\n← ${data.write_data}`;
  }
  if (name === 'WB') {
    if (!data.reg_write) return 'no write';
    return `x${data.rd} ← ${data.write_data}`;
  }
}
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML.encode())

    def do_POST(self):
        if self.path == "/api/simulate":
            length = int(self.headers["Content-Length"])
            body = json.loads(self.rfile.read(length))
            GLOBAL_DICT.clear()
            create_state("demo", body["instructions"])
            result = run_simulation("demo")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

    def log_message(self, format, *args):
        print(f"  {args[0]}")


if __name__ == "__main__":
    print("ArchReactor Demo: http://localhost:8000")
    HTTPServer(("", 8000), Handler).serve_forever()
