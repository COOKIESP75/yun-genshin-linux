#!/usr/bin/env node
/* 用系统 Chrome（headless + CDP）渲染宣传图：PNG + PDF，并做版面自检。
 * 用法: node render.mjs <html路径> <输出目录> [宽度] [高度]
 */
import { spawn } from 'node:child_process';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, basename } from 'node:path';

const htmlPath = resolve(process.argv[2] ?? 'poster.html');
const outDir = resolve(process.argv[3] ?? '.');
const W = parseInt(process.argv[4] ?? '1240', 10);
const H = parseInt(process.argv[5] ?? '1754', 10);
const PORT = 9333 + Math.floor(Math.random() * 400);
const profile = mkdtempSync(join(tmpdir(), 'poster-chrome-'));

const chrome = spawn('google-chrome', [
  '--headless=new', '--no-sandbox', '--disable-gpu', '--hide-scrollbars',
  '--disable-lcd-text', '--force-color-profile=srgb',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--no-first-run', '--no-default-browser-check', '--disable-extensions',
  `file://${htmlPath}`,
], { stdio: ['ignore', 'ignore', 'pipe'] });

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function targetWs() {
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const list = await r.json();
      const page = list.find(t => t.type === 'page' && t.webSocketDebuggerUrl);
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* not up yet */ }
    await sleep(250);
  }
  throw new Error('chrome devtools endpoint not reachable');
}

class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); this.events = []; }
  static async connect(url) {
    const ws = new WebSocket(url);
    const c = new CDP(ws);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && c.pending.has(msg.id)) {
        const { res, rej } = c.pending.get(msg.id); c.pending.delete(msg.id);
        msg.error ? rej(new Error(JSON.stringify(msg.error))) : res(msg.result);
      } else if (msg.method) c.events.push(msg);
    };
    return c;
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((res, rej) => {
      this.pending.set(id, { res, rej });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); rej(new Error('timeout ' + method)); } }, 60000);
    });
  }
}

try {
  const wsUrl = await targetWs();
  const cdp = await CDP.connect(wsUrl);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: W, height: H, deviceScaleFactor: 2, mobile: false,
  });
  await sleep(1200); // 等字体与布局稳定

  // ---- 版面自检 ----
  const probe = `(() => {
    const poster = document.querySelector('.poster') || document.querySelector('.banner');
    const content = document.querySelector('.content') || document.querySelector('.page') || document.body;
    const pr = poster.getBoundingClientRect();
    const cr = content.getBoundingClientRect();
    const out = {
      poster: {w: pr.width, h: pr.height, scrollH: poster.scrollHeight, scrollW: poster.scrollWidth},
      content: {h: cr.height, scrollH: content.scrollHeight, scrollW: content.scrollWidth},
      docScroll: {h: document.documentElement.scrollHeight, w: document.documentElement.scrollWidth},
      overflows: [], tiny: [], fonts: {},
    };
    for (const el of document.querySelectorAll('*')) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      if (r.bottom > pr.bottom + 0.6 || r.right > pr.right + 0.6 || r.top < pr.top - 0.6 || r.left < pr.left - 0.6) {
        out.overflows.push({sel: el.className || el.tagName, top: Math.round(r.top), bottom: Math.round(r.bottom), left: Math.round(r.left), right: Math.round(r.right)});
      }
      // 文本被裁剪检测
      if (el.children.length === 0 && el.textContent.trim() && (el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1)) {
        out.tiny.push({sel: el.className || el.tagName, sh: el.scrollHeight, ch: el.clientHeight, sw: el.scrollWidth, cw: el.clientWidth, txt: el.textContent.trim().slice(0, 28)});
      }
    }
    // 段落级溢出（文本超出自身盒子）
    for (const el of document.querySelectorAll('p,h1,h2,h3,.num,.lab,.chip,.step,.badge')) {
      const r = el.getBoundingClientRect();
      if (r.bottom > pr.bottom + 0.6) out.overflows.push({sel: 'late:' + (el.className || el.tagName), bottom: Math.round(r.bottom)});
    }
    const set = new Set();
    for (const el of document.querySelectorAll('*')) {
      const ff = getComputedStyle(el).fontFamily;
      set.add(ff.split(',')[0].replace(/["']/g,''));
    }
    out.fonts = [...set];
    // 顶层模块的垂直位置与间隙（找空洞）
    out.blocks = [];
    let prevBottom = 0;
    for (const el of content.children) {
      const r = el.getBoundingClientRect();
      out.blocks.push({
        sel: el.className || el.tagName,
        top: Math.round(r.top), bottom: Math.round(r.bottom), h: Math.round(r.height),
        gapAbove: Math.round(r.top - prevBottom),
      });
      prevBottom = r.bottom;
    }
    out.bottomSlack = Math.round(pr.bottom - prevBottom);
    // 流程条 chip 是否换行（最后一个 chip 单独占一行 = 排版缺陷）
    out.chips = [...document.querySelectorAll('.chip')].map(e => {
      const r = e.getBoundingClientRect();
      return {t: e.textContent.trim(), x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width)};
    });
    return JSON.stringify(out);
  })()`;
  const probeRes = await cdp.send('Runtime.evaluate', { expression: probe, returnByValue: true });
  const report = JSON.parse(probeRes.result.value);
  console.log('=== 版面自检 ===');
  console.log(JSON.stringify(report, null, 2));

  // ---- 截图 ----
  // 注意：不能用 captureBeyondViewport + clip（Chrome 会分块重栅格化，导致局部空白）。
  // 视口尺寸已等于页面尺寸，直接截视口即可完整且无错位。
  const shot = await cdp.send('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: false,
  });
  const pngPath = join(outDir, `${basename(htmlPath, '.html')}.png`);
  writeFileSync(pngPath, Buffer.from(shot.data, 'base64'));
  console.log('PNG:', pngPath);

  // ---- PDF ----
  const pdf = await cdp.send('Page.printToPDF', {
    printBackground: true, preferCSSPageSize: true,
    margin: { top: 0, right: 0, bottom: 0, left: 0 },
    pageRanges: '1',
  });
  const pdfPath = join(outDir, `${basename(htmlPath, '.html')}.pdf`);
  writeFileSync(pdfPath, Buffer.from(pdf.data, 'base64'));
  console.log('PDF:', pdfPath);

  await cdp.send('Browser.close').catch(() => {});
  chrome.kill('SIGTERM');
  process.exit(0);
} catch (e) {
  console.error('RENDER FAILED:', e.message);
  chrome.kill('SIGTERM');
  process.exit(1);
}
