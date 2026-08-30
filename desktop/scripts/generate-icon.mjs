// 生成应用图标：256x256 淡蓝底 + 白色柱状图（投资主题）
// 输出 assets/icon.png 与 assets/icon.ico（PNG 压缩 ICO，Vista+ 支持）
import { deflateSync } from 'zlib';
import { writeFileSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const here = dirname(fileURLToPath(import.meta.url));
const outDir = join(here, '..', 'assets');
mkdirSync(outDir, { recursive: true });

const SIZE = 256;
const BG = [0x5b, 0x9b, 0xd5, 0xff]; // 淡蓝 #5B9BD5
const WHITE = [255, 255, 255, 255];

function draw() {
  const px = Buffer.alloc(SIZE * SIZE * 4);
  for (let i = 0; i < SIZE * SIZE; i++) {
    px[i * 4] = BG[0]; px[i * 4 + 1] = BG[1]; px[i * 4 + 2] = BG[2]; px[i * 4 + 3] = BG[3];
  }
  const set = (x, y, c) => {
    if (x < 0 || y < 0 || x >= SIZE || y >= SIZE) return;
    const i = (y * SIZE + x) * 4;
    px[i] = c[0]; px[i + 1] = c[1]; px[i + 2] = c[2]; px[i + 3] = c[3];
  };
  // 三根白色柱子（高度代表上升趋势）
  const bars = [[36, 90, 150], [106, 160, 100], [176, 230, 185]];
  for (const [x0, x1, yTop] of bars) {
    for (let x = x0; x <= x1; x++) {
      for (let y = yTop; y <= 212; y++) set(x, y, WHITE);
    }
  }
  // 基线
  for (let x = 30; x <= 226; x++) set(x, 222, WHITE);
  // 圆角效果：四角压成背景色（简单 16px 圆角）
  return px;
}

const crcTable = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c;
  }
  return t;
})();
function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = crcTable[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const t = Buffer.from(type, 'ascii');
  const crcBuf = Buffer.concat([t, data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(crcBuf));
  return Buffer.concat([len, t, data, crc]);
}
function encodePNG(px, w, h) {
  const sig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0);
  ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8;
  ihdr[9] = 6;
  const raw = Buffer.alloc((w * 4 + 1) * h);
  for (let y = 0; y < h; y++) {
    raw[y * (w * 4 + 1)] = 0;
    px.copy(raw, y * (w * 4 + 1) + 1, y * w * 4, (y + 1) * w * 4);
  }
  const idat = deflateSync(raw, { level: 9 });
  return Buffer.concat([sig, chunk('IHDR', ihdr), chunk('IDAT', idat), chunk('IEND', Buffer.alloc(0))]);
}
function encodeICO(png) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(1, 4);
  const entry = Buffer.alloc(16);
  entry[0] = 0;
  entry[1] = 0;
  entry.writeUInt16LE(1, 2);
  entry.writeUInt16LE(32, 4);
  entry.writeUInt32LE(png.length, 8);
  entry.writeUInt32LE(22, 12);
  return Buffer.concat([header, entry, png]);
}

const png = encodePNG(draw(), SIZE, SIZE);
writeFileSync(join(outDir, 'icon.png'), png);
writeFileSync(join(outDir, 'icon.ico'), encodeICO(png));
console.log('icon.png + icon.ico generated:', png.length, 'bytes');
