import { marked } from 'marked'

marked.use({ gfm: true, breaks: true })

const ALLOWED_TAGS = new Set([
  'P', 'BR', 'STRONG', 'EM', 'DEL', 'UL', 'OL', 'LI', 'BLOCKQUOTE',
  'CODE', 'PRE', 'TABLE', 'THEAD', 'TBODY', 'TR', 'TH', 'TD',
  'H1', 'H2', 'H3', 'H4', 'HR', 'A', 'SUP', 'SPAN', 'DIV',
])
const ALLOWED_ATTRS = new Set(['href', 'title', 'class', 'data-fact-id'])

function safeUrl(value) {
  return /^(https?:|mailto:|#|\/)/i.test(value || '')
}

export function sanitizeHtml(html) {
  if (typeof DOMParser === 'undefined') return html
  const document = new DOMParser().parseFromString(`<template>${html}</template>`, 'text/html')
  const template = document.querySelector('template')
  for (const element of [...template.content.querySelectorAll('*')]) {
    if (!ALLOWED_TAGS.has(element.tagName)) {
      element.replaceWith(document.createTextNode(element.textContent || ''))
      continue
    }
    for (const attribute of [...element.attributes]) {
      if (!ALLOWED_ATTRS.has(attribute.name)) element.removeAttribute(attribute.name)
    }
    if (element.hasAttribute('class')) {
      const safeClasses = element.className.split(/\s+/).filter(name => (
        name === 'fx' || name === 'num' || name === 'num-up' || name === 'num-down' || name === 'table-wrap' || name === 'xlsx-dl' || /^language-[\w-]+$/.test(name)
      ))
      if (safeClasses.length) element.className = safeClasses.join(' ')
      else element.removeAttribute('class')
    }
    if (element.tagName === 'A') {
      if (!safeUrl(element.getAttribute('href'))) element.removeAttribute('href')
      else {
        element.setAttribute('target', '_blank')
        element.setAttribute('rel', 'noopener noreferrer')
      }
    }
  }
  return template.innerHTML
}

const NUMERIC_CELL = /^(?:[+\-−]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?|[+\-−]?\d+(?:\.\d+)?\s*亿)$/

function decorateDataHtml(html) {
  if (typeof DOMParser === 'undefined') return html
  const document = new DOMParser().parseFromString(`<template>${html}</template>`, 'text/html')
  const template = document.querySelector('template')
  for (const table of template.content.querySelectorAll('table')) {
    const rows = [...table.querySelectorAll('tbody tr')]
    const colCount = rows.reduce((max, row) => Math.max(max, row.children.length), 0)
    for (let index = 0; index < colCount; index += 1) {
      const cells = rows.map(row => row.children[index]).filter(Boolean)
      const numeric = cells.filter(cell => NUMERIC_CELL.test((cell.textContent || '').trim()))
      if (!cells.length || numeric.length < cells.length * 0.8) continue
      const indexLike = index === 0 && numeric.every(cell => /^\d{1,3}$/.test((cell.textContent || '').trim()))
      if (indexLike) continue
      for (const cell of numeric) {
        const text = (cell.textContent || '').trim()
        cell.classList.add('num')
        if (/^[−\-]/.test(text)) cell.classList.add('num-down')
        else if (/^\+/.test(text)) cell.classList.add('num-up')
      }
      for (const row of table.querySelectorAll('thead tr')) {
        const header = row.children[index]
        if (header) header.classList.add('num')
      }
    }
    const wrap = document.createElement('div')
    wrap.className = 'table-wrap'
    table.replaceWith(wrap)
    wrap.appendChild(table)
  }
  for (const anchor of template.content.querySelectorAll('a')) {
    if (/\/api\/v2\/runs\/[^/]+\/exports\//.test(anchor.getAttribute('href') || '')) {
      anchor.classList.add('xlsx-dl')
    }
  }
  return template.innerHTML
}

export function renderMarkdown(markdown) {
  return sanitizeHtml(decorateDataHtml(marked.parse(markdown || '')))
}
