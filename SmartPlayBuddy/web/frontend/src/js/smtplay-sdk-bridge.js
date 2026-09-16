import { Message } from './smtplay-sdk-message.js'

export { Message }

/**
 * 信封标记字段名。
 *
 * iframe 里除了 mod 自己的代码，还跑着浏览器扩展注入的 content script
 * （沉浸式翻译的 frame-bridge、Vue DevTools、钱包类等），它们同样用
 * window.postMessage 通信，载荷形状无法穷举。平台侧不做排除，改做正向识别：
 * SDK 每次初始化生成一个 128 位随机标记，握手时告知平台，之后每条消息都带着它。
 *
 * 标记值不是秘密——它就明文走在同一条信道上。它的作用是"几乎不可能偶然撞上"，
 * 让平台能确定无疑地分辨出业务消息。
 *
 * ⚠️ 字段名在 src/composables/useWSBridge.ts 有一份镜像，改这里必须同步改那里。
 */
const SMTPLAY_MARK = '__smtplay__'

function genNonce() {
  // crypto.getRandomValues 不受安全上下文限制，HTTP 下同样可用
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  let s = ''
  for (let i = 0; i < bytes.length; i++) s += bytes[i].toString(16).padStart(2, '0')
  return s
}

/**
 * 每个页面的 nonce 只能有一个：平台收到新握手会顶掉旧的。
 * 所以重复 new 会让前一个实例彻底失联，这里强制单例。
 */
let _instance = null

export class SmtplayWSBridge {
  constructor() {
    if (_instance) {
      console.warn(
        '[smtplay-sdk] SmtplayWSBridge 应当单例使用；重复创建会让前一个实例的标记失效，已返回原实例',
      )
      return _instance
    }

    this._listeners = new Set()
    this._pending = null
    this._nonce = genNonce()

    window.addEventListener('message', (e) => {
      const env = e.data
      if (!env || typeof env !== 'object' || env[SMTPLAY_MARK] !== this._nonce) return
      // 握手消息没有 payload；独立运行（非嵌入）时会收到自己发出的那一条，直接跳过
      if (!('payload' in env)) return

      const p = env.payload
      if (p instanceof ArrayBuffer || p instanceof Blob) {
        this._onBinary(p)
      } else {
        this._onText(p)
      }
    })

    // 握手必须早于任何 send()：平台在收到它之前会丢弃全部上行业务消息。
    // 与上面的 recv 监听器在同一个同步块内，postMessage 按 FIFO 入队，
    // 因此不存在"业务消息比握手先到平台"的情况。
    window.parent.postMessage({ [SMTPLAY_MARK]: this._nonce, hello: true }, '*')

    _instance = this
  }

  _onText(payload) {
    let msg
    try {
      msg = Message.fromRaw(payload)
    } catch { return }

    if (msg.data && typeof msg.data === 'object' && msg.data.__binary__) {
      delete msg.data.__binary__
      this._pending = msg
      return
    }
    this._emit(msg)
  }

  _onBinary(buffer) {
    if (!this._pending) return
    this._pending.binaryData = buffer
    this._emit(this._pending)
    this._pending = null
  }

  _emit(msg) {
    this._listeners.forEach(fn => fn(msg))
  }

  /**
   * 发送消息。
   * @param {Message} message
   */
  send(message) {
    if (!(message instanceof Message)) {
      message = Message.fromRaw(message)
    }
    const mark = { [SMTPLAY_MARK]: this._nonce }
    window.parent.postMessage({ ...mark, payload: message.toJSON() }, '*')
    if (message.binaryData) {
      // ArrayBuffer 放进信封由结构化克隆复制，与之前裸发同为一次拷贝，开销不变
      window.parent.postMessage({ ...mark, payload: message.binaryData }, '*')
    }
  }

  /**
   * 注册消息回调。回调参数为 Message 实例。
   * @param {(msg: Message) => void} fn
   * @returns {() => void} 取消注册的函数
   */
  recv(fn) {
    this._listeners.add(fn)
    return () => this._listeners.delete(fn)
  }

  is_embedded() {
    return window.parent !== window
  }
}
