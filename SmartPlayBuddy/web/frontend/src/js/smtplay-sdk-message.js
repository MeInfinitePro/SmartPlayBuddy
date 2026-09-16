const _encoder = new TextEncoder()
const _decoder = new TextDecoder()

// ─── Snowflake ID Generator ──────────────────────────────────────────────────

class SnowflakeGenerator {
  constructor(workerId = 0, datacenterId = 0) {
    this._workerId = BigInt(workerId & 0x1F)
    this._datacenterId = BigInt(datacenterId & 0x1F)
    this._seq = 0
    this._lastTs = -1n
    this._epoch = 1700000000000n
  }

  next() {
    let ts = BigInt(Date.now())
    if (ts === this._lastTs) {
      this._seq = (this._seq + 1) & 0xFFF
      if (this._seq === 0) while (BigInt(Date.now()) <= this._lastTs) ts = BigInt(Date.now())
    } else {
      this._seq = 0
    }
    this._lastTs = ts
    return (((ts - this._epoch) << 22n) | (this._datacenterId << 17n) | (this._workerId << 12n) | BigInt(this._seq)).toString()
  }
}

const _gen = new SnowflakeGenerator()

// ─── Base64 Codec ─────────────────────────────────────────────────────────────

function _u8ToB64(bytes) {
  let s = ''
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i])
  return btoa(s)
}

function _b64ToU8(b64) {
  const raw = atob(b64)
  const out = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return out
}

function _toBytes(data) {
  if (data instanceof Uint8Array) return data
  if (data instanceof ArrayBuffer) return new Uint8Array(data)
  if (ArrayBuffer.isView(data)) return new Uint8Array(data.buffer, data.byteOffset, data.byteLength)
  if (typeof data === 'string') return _encoder.encode(data)
  return _encoder.encode(JSON.stringify(data))
}

function _decodeDataField(b64) {
  if (b64 == null) return null
  if (typeof b64 !== 'string') return b64
  try {
    const str = _decoder.decode(_b64ToU8(b64))
    try { return JSON.parse(str) } catch { return str }
  } catch {
    return b64
  }
}

// ─── Message ──────────────────────────────────────────────────────────────────

export class Message {
  /**
   * @param {string}  type
   * @param {string}  action
   * @param {*}       [data]        - 业务数据，send 时自动 Base64 编码
   * @param {Object}  [opts]
   * @param {string}  [opts.from]
   * @param {string}  [opts.to]
   * @param {string}  [opts.requestId]  - 不传则雪花算法自动生成
   * @param {number}  [opts.timestamp]  - 不传则自动取当前毫秒时间戳
   * @param {boolean} [opts.binary]     - 标记后续跟随二进制帧
   */
  constructor(type, action, data = null, opts = {}) {
    this.type = type
    this.action = action
    this.data = data
    this.from = opts.from ?? null
    this.to = opts.to ?? null
    this.requestId = opts.requestId ?? _gen.next()
    this.timestamp = opts.timestamp ?? Date.now()
    this.binary = opts.binary ?? false
    this.binaryData = null
  }

  /**
   * 从服务端原始 JSON（字符串或已解析对象）反序列化。
   * Data 字段自动 Base64 解码。
   */
  static fromRaw(raw) {
    if (typeof raw === 'string') {
      const obj = JSON.parse(raw)
      return new Message(
        obj.type,
        obj.action,
        _decodeDataField(obj.data),
        {
          from: obj.from ?? null,
          to: obj.to ?? null,
          requestId: obj.requestId ?? null,
          timestamp: obj.timestamp ?? 0,
          binary: obj.binary ?? false,
        }
      )
    }

    return new Message(
      raw.type,
      raw.action,
      raw.data ?? null,
      {
        from: raw.from ?? null,
        to: raw.to ?? null,
        requestId: raw.requestId ?? null,
        timestamp: raw.timestamp ?? 0,
        binary: raw.binary ?? false,
      }
    )
  }

  /**
   * 序列化为服务端 JSON 线格式（返回普通对象，供 JSON.stringify 或 postMessage）。
   * Data 字段自动 Base64 编码。
   */
  toJSON() {
    const obj = {
      type: this.type,
      action: this.action,
      timestamp: this.timestamp,
    }
    if (this.from) obj.from = this.from
    if (this.to) obj.to = this.to
    if (this.requestId) obj.requestId = this.requestId
    if (this.binary) obj.binary = true
    if (this.data != null) obj.data = _u8ToB64(_toBytes(this.data))
    return obj
  }
}
