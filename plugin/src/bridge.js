import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { mkdirSync } from 'node:fs';

/** One private serial Python worker. Never opens a port or launches a shell. */
export class CoreBridge {
  constructor({ python = 'python', home, coreRoot, timeoutMs = 30000, onMemoryChange }) {
    this.options = { python, home, coreRoot, timeoutMs };
    this.onMemoryChange = onMemoryChange;
    this.reportsMemoryChanges = false;
    this.pending = new Map(); this.nextId = 1; this.child = null; this.closed = false;
  }
  start() {
    if (this.closed) throw new Error('memory bridge closed');
    if (this.child) return;
    const { python, home, coreRoot } = this.options;
    mkdirSync(home, { recursive: true });
    const child = spawn(python, ['-X', 'utf8', '-m', 'memory_core.plugin_bridge', '--home', home], {
      // Windows cannot rename an installed package used as a child's cwd.
      // Keep the worker in the durable data directory; PYTHONPATH locates code.
      cwd: home, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONUTF8: '1', PYTHONPATH: coreRoot },
    });
    this.child = child;
    this.reportsMemoryChanges = false;
    let lastRevision;
    const fail = error => {
      if (this.child === child) this.child = null;
      for (const [id, item] of this.pending) {
        if (item.child !== child) continue;
        clearTimeout(item.timer); item.reject(error); this.pending.delete(id);
      }
    };
    child.on('error', fail);
    child.on('exit', () => fail(new Error('memory worker exited; durable work resumes on next use')));
    // Deliberately keep stderr out of protocol/stdout and out of model context.
    child.stderr.on('data', data => { this.lastError = String(data).slice(-1500); });
    createInterface({ input: child.stdout }).on('line', line => {
      let value;
      try { value = JSON.parse(line); } catch { child.kill(); fail(new Error('invalid memory worker protocol')); return; }
      const item = this.pending.get(value.id);
      if (!item || item.child !== child) return;
      clearTimeout(item.timer); this.pending.delete(value.id);
      if (Number.isSafeInteger(value.memory_revision)) {
        this.reportsMemoryChanges = true;
        if (lastRevision !== value.memory_revision) {
          lastRevision = value.memory_revision;
          this.onMemoryChange?.();
        }
      }
      value.error ? item.reject(new Error(value.error.message)) : item.resolve(value.result);
    });
  }
  request(op, args = {}) {
    this.start(); const id = this.nextId++; const child = this.child;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id); reject(new Error('memory worker timeout; request not blindly replayed'));
        if (this.child === child) { this.child = null; child.kill(); }
      }, this.options.timeoutMs);
      this.pending.set(id, { resolve, reject, timer, child });
      child.stdin.write(JSON.stringify({ id, op, args }) + '\n', error => {
        if (!error) return;
        clearTimeout(timer); this.pending.delete(id); reject(error);
      });
    });
  }
  async close() {
    this.closed = true;
    const child = this.child; this.child = null;
    if (!child) return;
    const exit = new Promise(resolve => child.once('exit', resolve));
    child.stdin.end();
    const timer = setTimeout(() => child.kill(), 2000);
    await exit; clearTimeout(timer);
  }
}
