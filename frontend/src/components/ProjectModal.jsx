import React, { useEffect, useState } from 'react'
import { Modal, Field } from './ui.jsx'

const EMPTY = {
  title: '',
  kpi_target: '',
  kpi_metric: '',
  kpi_direction: 'increase',
  domain: '',
  constraints: '',
}

export default function ProjectModal({
  initial,
  currentUser,
  canManageMembers = false,
  onClose,
  onSave,
  onLoadMembers,
  onInviteMember,
  onRemoveMember,
}) {
  const [form, setForm] = useState({ ...EMPTY, ...(initial || {}) })
  const [saving, setSaving] = useState(false)
  const [members, setMembers] = useState([])
  const [membersLoading, setMembersLoading] = useState(false)
  const [memberUsername, setMemberUsername] = useState('')
  const [memberStatus, setMemberStatus] = useState('')
  const isEdit = Boolean(initial && initial.id)
  const canEditProject = !isEdit || initial?.can_manage_project || initial?.current_user_role === 'owner'

  const updateField = (key) => (event) => setForm({ ...form, [key]: event.target.value })

  async function loadMembers() {
    if (!isEdit || !onLoadMembers) return
    setMembersLoading(true)
    setMemberStatus('')
    try {
      const rows = await onLoadMembers(initial.id)
      setMembers(Array.isArray(rows) ? rows : [])
    } catch (error) {
      setMemberStatus(error.message)
    } finally {
      setMembersLoading(false)
    }
  }

  useEffect(() => {
    loadMembers()
  }, [initial?.id])

  async function submit() {
    if (!canEditProject || !form.title.trim() || !form.kpi_target.trim()) return
    setSaving(true)
    try {
      await onSave(form)
      onClose()
    } finally {
      setSaving(false)
    }
  }

  async function inviteMember() {
    const username = memberUsername.trim()
    if (!username || !canManageMembers || !onInviteMember) return
    setMemberStatus('')
    try {
      await onInviteMember(initial.id, username)
      setMemberUsername('')
      await loadMembers()
    } catch (error) {
      setMemberStatus(error.message)
    }
  }

  async function removeMember(member) {
    if (!member?.user_id || !canManageMembers || !onRemoveMember) return
    const label = member.user?.display_name || member.user?.username || `user ${member.user_id}`
    if (!window.confirm(`Удалить участника ${label} из проекта?`)) return
    setMemberStatus('')
    try {
      await onRemoveMember(initial.id, member.user_id)
      await loadMembers()
    } catch (error) {
      setMemberStatus(error.message)
    }
  }

  return (
    <Modal
      title={isEdit ? 'Параметры проекта' : 'Новый проект'}
      onClose={onClose}
      footer={(
        <>
          <button className="btn secondary" onClick={onClose}>
            Отмена
          </button>
          {canEditProject && (
            <button className="btn primary" disabled={saving} onClick={submit}>
              {saving ? 'Сохранение...' : isEdit ? 'Сохранить' : 'Создать проект'}
            </button>
          )}
        </>
      )}
    >
      <Field label="Название проекта *">
        <input
          value={form.title}
          onChange={updateField('title')}
          disabled={!canEditProject}
          placeholder="Например: коррозионностойкий Ni-сплав"
        />
      </Field>

      <Field label="Целевой показатель (KPI) *">
        <textarea
          value={form.kpi_target}
          onChange={updateField('kpi_target')}
          disabled={!canEditProject}
          rows={3}
          placeholder="Например: снизить скорость коррозии сплава в 20% H2SO4 при 80 C."
        />
      </Field>

      <div className="row">
        <Field label="Измеримая метрика">
          <input
            value={form.kpi_metric}
            onChange={updateField('kpi_metric')}
            disabled={!canEditProject}
            placeholder="Скорость коррозии, мм/год"
          />
        </Field>
        <Field label="Направление">
          <select value={form.kpi_direction} onChange={updateField('kpi_direction')} disabled={!canEditProject}>
            <option value="increase">Увеличить</option>
            <option value="decrease">Снизить</option>
          </select>
        </Field>
      </div>

      <Field label="Область / контекст">
        <input
          value={form.domain}
          onChange={updateField('domain')}
          disabled={!canEditProject}
          placeholder="Металлургия, коррозия, никелевые сплавы"
        />
      </Field>

      <Field label="Ограничения и доступные ресурсы">
        <textarea
          value={form.constraints}
          onChange={updateField('constraints')}
          disabled={!canEditProject}
          rows={3}
          placeholder="Доступное оборудование, бюджет, сроки и ограничения по материалам"
        />
      </Field>

      {isEdit && (
        <section className="project-members">
          <div className="project-members__head">
            <div>
              <h3>Участники проекта</h3>
              <p>Owner управляет свойствами проекта и приглашениями. Member может работать с содержимым проекта.</p>
            </div>
            {membersLoading && <span>Загрузка...</span>}
          </div>

          <div className="project-members__list">
            {members.map((member) => {
              const user = member.user || {}
              const isOwner = member.role === 'owner'
              const isSelf = currentUser?.id === member.user_id
              return (
                <div className="project-members__row" key={member.id || member.user_id}>
                  <div>
                    <strong>{user.display_name || user.username || `User ${member.user_id}`}</strong>
                    <span>@{user.username || member.user_id}</span>
                  </div>
                  <mark>{member.role}</mark>
                  {canManageMembers && !isOwner && !isSelf && (
                    <button className="btn secondary" type="button" onClick={() => removeMember(member)}>
                      Убрать
                    </button>
                  )}
                </div>
              )
            })}
            {!membersLoading && members.length === 0 && (
              <div className="project-members__empty">Участников пока нет.</div>
            )}
          </div>

          {canManageMembers && (
            <div className="project-members__invite">
              <input
                value={memberUsername}
                onChange={(event) => {
                  setMemberUsername(event.target.value)
                  setMemberStatus('')
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    inviteMember()
                  }
                }}
                placeholder="Ник пользователя"
              />
              <button className="btn primary" type="button" onClick={inviteMember} disabled={!memberUsername.trim()}>
                Добавить member
              </button>
            </div>
          )}

          {memberStatus && <div className="project-members__status">{memberStatus}</div>}
        </section>
      )}
    </Modal>
  )
}
