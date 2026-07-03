import React, { useState } from 'react'
import { Modal, Field, TYPE_LABEL } from './ui.jsx'

const EMPTY = {
  title: '',
  content: '',
  source_type: 'literature',
  authors: '',
  year: '',
  reference: '',
}

export default function KnowledgePanel({ sources, onAdd, onDelete }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const [saving, setSaving] = useState(false)

  const updateField = (key) => (e) => setForm({ ...form, [key]: e.target.value })

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
        <button className="btn primary" onClick={() => setOpen(true)}>
          Добавить источник
        </button>
      </div>

      <div className="card-body knowledge-panel">
        {sources.length === 0 && (
          <p className="section-hint">
            Добавьте статьи, отчёты и экспериментальные заметки. Эти материалы станут основой retrieval и объяснений для гипотез.
          </p>
        )}

        {sources.map((s) => (
          <article className="source" key={s.id}>
            <div className="s-top">
              <span className={`type-tag type-${s.source_type}`}>{TYPE_LABEL[s.source_type] || s.source_type}</span>
              <span className="s-title">{s.title}</span>
              <button className="btn secondary btn-compact" title="Удалить источник" onClick={() => onDelete(s.id)}>
                Удалить
              </button>
            </div>

            <div className="s-excerpt">
              {(s.authors || s.year) && (
                <b>
                  {[s.authors, s.year].filter(Boolean).join(', ')}
                  {'. '}
                </b>
              )}
              {s.excerpt}
            </div>
          </article>
        ))}
      </div>

      {open && (
        <Modal
          title="Новый источник знаний"
          onClose={() => setOpen(false)}
          footer={(
            <>
              <button className="btn secondary" onClick={() => setOpen(false)}>
                Отмена
              </button>
              <button className="btn primary" disabled={saving} onClick={submit}>
                {saving ? 'Сохранение…' : 'Добавить'}
              </button>
            </>
          )}
        >
          <Field label="Тип источника">
            <select value={form.source_type} onChange={updateField('source_type')}>
              <option value="literature">Литература / статья</option>
              <option value="report">Внутренний отчёт</option>
              <option value="experiment">Эксперимент / лаб. данные</option>
            </select>
          </Field>

          <Field label="Заголовок *">
            <input value={form.title} onChange={updateField('title')} placeholder="Название статьи или отчёта" />
          </Field>

          <div className="row">
            <Field label="Авторы / подразделение">
              <input value={form.authors} onChange={updateField('authors')} placeholder="Petrov et al." />
            </Field>
            <Field label="Год">
              <input value={form.year} onChange={updateField('year')} placeholder="2025" className="num-input" />
            </Field>
          </div>

          <Field label="Ссылка / DOI / инвентарный номер">
            <input value={form.reference} onChange={updateField('reference')} placeholder="DOI, ссылка или номер отчёта" />
          </Field>

          <Field label="Содержание / аннотация *">
            <textarea
              value={form.content}
              onChange={updateField('content')}
              rows={7}
              placeholder="Вставьте текст, аннотацию или ключевые выводы источника…"
            />
          </Field>
        </Modal>
      )}
    </div>
  )
}
