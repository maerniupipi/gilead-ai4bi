export function yieldToBrowser() {
  return new Promise(resolve => setTimeout(resolve, 0))
}

export function deferRender(render) {
  let cancelled = false
  let idle = null
  const run = () => { if (!cancelled) render() }
  const timer = setTimeout(() => {
    if (globalThis.requestIdleCallback) idle = globalThis.requestIdleCallback(run, { timeout: 200 })
    else run()
  }, 32)
  return () => {
    cancelled = true
    clearTimeout(timer)
    if (idle !== null) globalThis.cancelIdleCallback?.(idle)
  }
}
