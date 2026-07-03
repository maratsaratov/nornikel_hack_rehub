import React, { useState } from 'react'
import { Modal, Field, TYPE_LABEL } from './ui.jsx'

const EMPTY = { title: '', content: '', source_type: 'literature', authors: '', year: '', reference: '' }

export default function KnowledgePanel({ sources, onAdd, onDelete }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const [saving, setSaving] = useState(false)

  const upd = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  async function submit() {
    if (!form.title.trim() || !form.content.trim()) return
    setSaving(true)
    try {
      await onAdd({ ...form, year: form.year ? parseInt(form.year, 10) : null })
      setForm(EMPTY)
      setOpen(false)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <h3>База знаний</h3>
        <span className="count">{sources.length}</span>
        <div className="spacer" />
        <button className="btn sm" onClick={() => setOpen(true)}>+ Источник</button>
      </div>
      <div className="card-body" style={{ paddingTop: 4, paddingBottom: 4 }}>
        {sources.length === 0 && (
          <p className="section-hint" style={{ padding: '10px 0' }}>
            Добавьте литературу, отчёты и эксперименты — на их основе будут строиться гипотезы.
          </p>
        )}
        {sources.map((s) => (
          <div className="source" key={s.id}>
            <div className="s-top">
              <span className={`type-tag type-${s.source_type}`}>{TYPE_LABEL[s.source_type] || s.source_type}</span>
              <span className="s-title">{s.title}</span>
              <button className="btn ghost sm danger" title="Удалить" onClick={() => onDelete(s.id)}>✕</button>
            </div>
            <div className="s-excerpt">
              {(s.authors || s.year) && (
                <b style={{ color: 'var(--ink-soft)' }}>
                  {[s.authors, s.year].filter(Boolean).join(', ')} —{' '}
                </b>
              )}
              {s.excerpt}
            </div>
          </div>
        ))}
      </div>

      {open && (
        <Modal
          title="Новый источник знаний"
          onClose={() => setOpen(false)}
          footer={
            <>
              <button className="btn" onClick={() => setOpen(false)}>Отмена</button>
              <button className="btn primary" disabled={saving} onClick={submit}>
                {saving ? 'Сохранение…' : 'Добавить'}
              </button>
            </>
          }
        >
          <Field label="Тип источника">
            <select value={form.source_type} onChange={upd('source_type')}>
              <option value="literature">Литература / статья</option>
              <option value="report">Внутренний отчёт</option>
              <option value="experiment">Эксперимент / лаб. данные</option>
            </select>
          </Field>
          <Field label="Заголовок *">
            <input value={form.title} onChange={upd('title')} placeholder="Название статьи / отчёта" />
          </Field>
          <div className="row">
            <Field label="Авторы / подразделение">
              <input value={form.authors} onChange={upd('authors')} placeholder="Petrov et al." />
            </Field>
            <Field label="Год">
              <input value={form.year} onChange={upd('year')} placeholder="2023" className="num-input" />
            </Field>
          </div>
          <Field label="Ссылка / DOI / инв. номер">
            <input value={form.reference} onChange={upd('reference')} placeholder="DOI, ссылка или № отчёта" />
          </Field>
          <Field label="Содержание / аннотация *">
            <textarea
              value={form.content}
              onChange={upd('content')}
              rows={7}
              placeholder="Вставьте текст, аннотацию или ключевые выводы источника…"
            />
          </Field>
        </Modal>
      )}
    </div>
  )
}
