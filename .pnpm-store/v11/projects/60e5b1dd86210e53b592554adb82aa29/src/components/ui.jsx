import React, { useEffect } from 'react'

export function Modal({ title, children, onClose, footer, className = '' }) {
  useEffect(() => {
    const handler = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div className="modal-overlay" onMouseDown={onClose}>
      <div className={`modal ${className}`.trim()} onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>{title}</h2>
          <div className="spacer" />
          <button className="btn secondary btn-close" onClick={onClose} aria-label="Закрыть окно">
            ×
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}

export function Field({ label, children }) {
  return (
    <div className="field">
      {label && <label>{label}</label>}
      {children}
    </div>
  )
}

export function Toast({ toast }) {
  if (!toast) return null
  return <div className={`toast ${toast.type}`}>{toast.msg}</div>
}

export const TYPE_LABEL = {
  literature: 'Литература',
  report: 'Отчёт',
  experiment: 'Эксперимент',
}
