export function decorateAnswerTables(html, allowPin = false) {
  if (typeof DOMParser === 'undefined') return String(html || '')
  const document = new DOMParser().parseFromString(`<template>${html || ''}</template>`, 'text/html')
  const template = document.querySelector('template')
  for (const [index, table] of [...template.content.querySelectorAll('table')].entries()) {
    const toolbar = document.createElement('div')
    toolbar.className = 'answer-table-actions'
    const label = document.createElement('span')
    label.textContent = '数据表'
    toolbar.appendChild(label)
    if (allowPin) {
      const button = document.createElement('button')
      button.type = 'button'
      button.dataset.answerTable = String(index)
      button.textContent = '＋ 表格加入看板'
      toolbar.appendChild(button)
    }
    table.before(toolbar)
  }
  return template.innerHTML
}
