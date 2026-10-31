import { deflateSync } from 'node:zlib'

/** CRC-32 (ISO 3309), as PNG chunks need it. */
const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
  return c >>> 0
})

function crc32(data: Buffer): number {
  let c = 0xffffffff
  for (const byte of data) c = CRC_TABLE[(c ^ byte) & 0xff]! ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}

function chunk(type: string, data: Buffer): Buffer {
  const length = Buffer.alloc(4)
  length.writeUInt32BE(data.length)
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data])
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(body))
  return Buffer.concat([length, body, crc])
}

/**
 * A valid RGB PNG of `width` × `height` with a simple two-colour gradient, built in memory so
 * upload tests need no fixture files.
 */
export function makePng(width = 320, height = 180): Buffer {
  const header = Buffer.alloc(13)
  header.writeUInt32BE(width, 0)
  header.writeUInt32BE(height, 4)
  header[8] = 8 // bit depth
  header[9] = 2 // colour type: RGB
  // compression, filter and interlace methods stay 0

  const row = 1 + width * 3
  const pixels = Buffer.alloc(row * height)
  for (let y = 0; y < height; y++) {
    pixels[y * row] = 0 // filter: none
    for (let x = 0; x < width; x++) {
      const at = y * row + 1 + x * 3
      pixels[at] = Math.round((x / width) * 255)
      pixels[at + 1] = 120
      pixels[at + 2] = Math.round((y / height) * 255)
    }
  }

  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', header),
    chunk('IDAT', deflateSync(pixels)),
    chunk('IEND', Buffer.alloc(0)),
  ])
}
