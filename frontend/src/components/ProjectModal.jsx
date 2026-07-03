import React, { useState } from 'react'
import { Modal, Field } from './ui.jsx'

const EMPTY = {
  title: '',
  kpi_target: '',
  kpi_metric: '',
  kpi_direction: 'increase',
  domain: '',
  constraints: '',
}

export default function ProjectModal({ initial, onClose, onSave }) {
  const [form, setForm] = useState({ ...EMPTY, ...(initial || {}) })
  const [saving, setSaving] = useState(false)
  const isEdit = Boolean(initial && initial.id)

  const updateField = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  async function submit() {
    if (!form.title.trim() || !form.kpi_target.trim()) return
    setSaving(true)
    try {
      await onSave(form)
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={isEdit ? 'Параметры проекта' : 'Новый НИОКР-проект'}
      onClose={onClose}
      footer={(
        <>
          <button className="btn secondary" onClick={onClose}>
            Отмена
          </button>
          <button className="btn primary" disabled={saving} onClick={submit}>
            {saving ? 'Сохранение…' : isEdit ? 'Сохранить' : 'Создать проект'}
          </button>
        </>
      )}
    >
      <Field label="Название проекта *">
        <input value={form.title} onChange={updateField('title')} placeholder="Например: коррозионностойкий Ni-сплав" />
      </Field>

      <Field label="Целевой показатель (KPI) *">
        <textarea
          value={form.kpi_target}
          onChange={updateField('kpi_target')}
          rows={3}
          placeholder="Например: снизить скорость коррозии сплава в 20% H2SO4 при 80 °C, сохранив технологичность."
        />
      </Field>

      <div className="row">
        <Field label="Измеримая метрика">
          <input value={form.kpi_metric} onChange={updateField('kpi_metric')} placeholder="Скорость коррозии, мм/год" />
        </Field>
        <Field label="Направление">
          <select value={form.kpi_direction} onChange={updateField('kpi_direction')}>
            <option value="increase">Увеличить</option>
            <option value="decrease">Снизить</option>
          </select>
        </Field>
      </div>

      <Field label="Область / контекст">
        <input value={form.domain} onChange={updateField('domain')} placeholder="Металлургия, коррозия, никелевые сплавы" />
      </Field>

      <Field label="Ограничения и доступные ресурсы">
        <textarea
          value={form.constraints}
          onChange={updateField('constraints')}
          rows={3}
          placeholder="Доступное оборудование, бюджет, сроки и ограничения по материалам…"
        />
      </Field>
    </Modal>
  )
}
