import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Modal } from './ui.jsx'

const SCENE_WIDTH = 980
const SCENE_HEIGHT = 700
const MAX_EVIDENCE_NODES = 4
const MAX_TAG_NODES = 4

const TYPE_LABELS = {
  hypothesis: 'Гипотеза',
  goal: 'Цель',
  impact: 'Эффект',
  mechanism: 'Механизм',
  validation: 'Проверка',
  risk: 'Риск',
  constraint: 'Ограничение',
  evidence: 'Основание',
  tag: 'Тег',
}

const EDGE_LABELS = {
  targets: 'Направлена на цель',
  produces: 'Даёт ожидаемый эффект',
  explains: 'Объясняет механизм',
  tests: 'Проверяется через план',
  threatens: 'Создаёт неопределённость',
  limits: 'Ограничивает эксперимент',
  supports: 'Поддерживает гипотезу',
  describes: 'Описывает тему',
}

const SLOT_POSITIONS = {
  goal: [{ x: 490, y: 88 }],
  mechanism: [{ x: 234, y: 236 }],
  validation: [{ x: 748, y: 232 }],
  impact: [{ x: 310, y: 552 }],
  risk: [{ x: 688, y: 552 }],
  constraint: [{ x: 826, y: 388 }],
  evidence: [
    { x: 332, y: 172 },
    { x: 645, y: 174 },
    { x: 316, y: 426 },
    { x: 652, y: 426 },
    { x: 490, y: 620 },
  ],
  tag: [
    { x: 132, y: 170 },
    { x: 852, y: 176 },
    { x: 146, y: 598 },
    { x: 834, y: 602 },
    { x: 492, y: 664 },
  ],
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value))
}

function compactText(value) {
  if (Array.isArray(value)) return value.filter(Boolean).join(', ')
  if (value === null || value === undefined) return ''
  return String(value).replace(/\s+/g, ' ').trim()
}

function shortenText(value, limit = 132) {
  const text = compactText(value)
  if (!text) return ''
  return text.length > limit ? `${text.slice(0, limit - 1).trim()}…` : text
}

function createSeed(value) {
  return String(value || 'roadmap').split('').reduce((total, char, index) => (
    total + char.charCodeAt(0) * (index + 3)
  ), 0)
}

function withOffset(point, seed, index, spread = 18) {
  if (!point) {
    return {
      x: SCENE_WIDTH / 2,
      y: SCENE_HEIGHT / 2,
    }
  }

  const angle = (seed * 0.17 + index * 1.13) % (Math.PI * 2)
  return {
    x: point.x + Math.cos(angle) * spread,
    y: point.y + Math.sin(angle) * spread,
  }
}

function parseScore(value) {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? Math.round(numeric) : null
}

function normalizeEvidence(item, index) {
  const title = compactText(item?.title || item?.source || `Источник ${index + 1}`)
  const snippet = compactText(item?.snippet)
  const relevance = compactText(item?.relevance)

  return {
    title,
    shortLabel: shortenText(title, 32),
    description: snippet || relevance || 'Источник использовался как supporting context для гипотезы.',
    relevance,
    sourceId: item?.source_id,
  }
}

function normalizeFallbackEvidence(item, index) {
  const title = compactText(item?.title || `Источник ${index + 1}`)
  const terms = Array.isArray(item?.terms) ? item.terms.filter(Boolean).join(', ') : ''
  const scoreParts = []

  if (typeof item?.score === 'number') scoreParts.push(`score ${item.score.toFixed(3)}`)
  if (terms) scoreParts.push(terms)

  return {
    title,
    shortLabel: shortenText(title, 32),
    description: scoreParts.join(' • ') || 'Источник попал в retrieval-контекст последнего запуска.',
    relevance: 'Контекст последнего запуска',
    sourceId: item?.source_id,
  }
}

function buildRoadmapGraph(hypothesis, project, retrieved = []) {
  const nodes = []
  const edges = []
  const positions = {}
  const seed = createSeed(hypothesis?.id)
  let slotIndex = 0

  const addNode = (node, position) => {
    nodes.push(node)
    positions[node.id] = position
  }

  const addEdge = (source, target, type) => {
    edges.push({
      id: `${source}->${target}:${type}`,
      source,
      target,
      type,
      label: EDGE_LABELS[type],
    })
  }

  const hypothesisId = `hypothesis-${hypothesis.id}`

  addNode({
    id: hypothesisId,
    type: 'hypothesis',
    label: compactText(hypothesis.statement) || 'Гипотеза без формулировки',
    shortLabel: shortenText(hypothesis.statement, 92) || 'Гипотеза без формулировки',
    payload: {
      title: compactText(hypothesis.statement) || 'Гипотеза без формулировки',
      description: compactText(hypothesis.rationale) || compactText(hypothesis.mechanism) || 'Центральная идея гипотезы и точка сборки всей дорожной карты.',
      score: parseScore(hypothesis._composite ? hypothesis._composite * 10 : null),
      tags: hypothesis.tags || [],
    },
  }, {
    x: SCENE_WIDTH / 2,
    y: SCENE_HEIGHT / 2 - 30,
  })

  if (compactText(project?.kpi_target)) {
    const goalId = `goal-${hypothesis.id}`
    addNode({
      id: goalId,
      type: 'goal',
      label: 'Цель / KPI',
      shortLabel: 'Цель / KPI',
      payload: {
        title: 'Цель проекта',
        description: compactText(project.kpi_target),
        metric: compactText(project.kpi_metric),
      },
    }, SLOT_POSITIONS.goal[0])
    addEdge(hypothesisId, goalId, 'targets')
  }

  const impactDescription = compactText(hypothesis.goal_link || hypothesis.rationales?.value || hypothesis.value_rationale)
  if (impactDescription) {
    const impactId = `impact-${hypothesis.id}`
    addNode({
      id: impactId,
      type: 'impact',
      label: 'Ожидаемый эффект',
      shortLabel: 'Ожидаемый эффект',
      payload: {
        title: 'Ожидаемый эффект',
        description: impactDescription,
        score: parseScore(hypothesis.scores?.value),
      },
    }, SLOT_POSITIONS.impact[0])
    addEdge(hypothesisId, impactId, 'produces')
  }

  if (compactText(hypothesis.mechanism)) {
    const mechanismId = `mechanism-${hypothesis.id}`
    addNode({
      id: mechanismId,
      type: 'mechanism',
      label: 'Механизм',
      shortLabel: 'Механизм',
      payload: {
        title: 'Предполагаемый механизм',
        description: compactText(hypothesis.mechanism),
      },
    }, SLOT_POSITIONS.mechanism[0])
    addEdge(mechanismId, hypothesisId, 'explains')
  }

  if (compactText(hypothesis.validation)) {
    const validationId = `validation-${hypothesis.id}`
    addNode({
      id: validationId,
      type: 'validation',
      label: 'План проверки',
      shortLabel: 'План проверки',
      payload: {
        title: 'Как проверяем гипотезу',
        description: compactText(hypothesis.validation),
        score: parseScore(hypothesis.scores?.feasibility),
      },
    }, SLOT_POSITIONS.validation[0])
    addEdge(validationId, hypothesisId, 'tests')

    if (compactText(project?.constraints)) {
      const constraintId = `constraint-${hypothesis.id}`
      addNode({
        id: constraintId,
        type: 'constraint',
        label: 'Ограничения',
        shortLabel: 'Ограничения',
        payload: {
          title: 'Ограничения проекта',
          description: compactText(project.constraints),
        },
      }, SLOT_POSITIONS.constraint[0])
      addEdge(constraintId, validationId, 'limits')
    }
  } else if (compactText(project?.constraints)) {
    const constraintId = `constraint-${hypothesis.id}`
    addNode({
      id: constraintId,
      type: 'constraint',
      label: 'Ограничения',
      shortLabel: 'Ограничения',
      payload: {
        title: 'Ограничения проекта',
        description: compactText(project.constraints),
      },
    }, SLOT_POSITIONS.constraint[0])
    addEdge(constraintId, hypothesisId, 'limits')
  }

  const riskDescription = compactText(hypothesis.rationales?.risk || hypothesis.risk_rationale)
  if (riskDescription || Number.isFinite(Number(hypothesis.scores?.risk))) {
    const riskId = `risk-${hypothesis.id}`
    addNode({
      id: riskId,
      type: 'risk',
      label: 'Риски',
      shortLabel: Number.isFinite(Number(hypothesis.scores?.risk))
        ? `Риск ${Math.round(hypothesis.scores.risk)}/100`
        : 'Риски',
      payload: {
        title: 'Ключевой риск',
        description: riskDescription || 'Для этой гипотезы модель оценила риск, но не дала отдельное текстовое пояснение.',
        score: parseScore(hypothesis.scores?.risk),
      },
    }, SLOT_POSITIONS.risk[0])
    addEdge(riskId, hypothesisId, 'threatens')
  }

  const evidenceItems = Array.isArray(hypothesis.evidence) && hypothesis.evidence.length > 0
    ? hypothesis.evidence.map(normalizeEvidence)
    : (retrieved || []).slice(0, MAX_EVIDENCE_NODES + 2).map(normalizeFallbackEvidence)

  evidenceItems.slice(0, MAX_EVIDENCE_NODES).forEach((item, index) => {
    const nodeId = `evidence-${hypothesis.id}-${index}`
    addNode({
      id: nodeId,
      type: 'evidence',
      label: item.title,
      shortLabel: item.shortLabel,
      payload: {
        title: item.title,
        description: item.description,
        relevance: item.relevance,
        sourceId: item.sourceId,
      },
    }, withOffset(SLOT_POSITIONS.evidence[index], seed, slotIndex++))
    addEdge(nodeId, hypothesisId, 'supports')
  })

  if (evidenceItems.length > MAX_EVIDENCE_NODES) {
    const hiddenCount = evidenceItems.length - MAX_EVIDENCE_NODES
    const nodeId = `evidence-${hypothesis.id}-more`
    addNode({
      id: nodeId,
      type: 'evidence',
      label: `+${hiddenCount} источника`,
      shortLabel: `+${hiddenCount} источника`,
      payload: {
        title: `Дополнительные основания (${hiddenCount})`,
        description: evidenceItems
          .slice(MAX_EVIDENCE_NODES)
          .map((item) => item.title)
          .join(' • '),
      },
    }, withOffset(SLOT_POSITIONS.evidence[4], seed, slotIndex++, 12))
    addEdge(nodeId, hypothesisId, 'supports')
  }

  const tags = Array.isArray(hypothesis.tags) ? hypothesis.tags.filter(Boolean) : []
  tags.slice(0, MAX_TAG_NODES).forEach((tag, index) => {
    const nodeId = `tag-${hypothesis.id}-${index}`
    addNode({
      id: nodeId,
      type: 'tag',
      label: compactText(tag),
      shortLabel: shortenText(tag, 22),
      payload: {
        title: compactText(tag),
        description: 'Тематический маркер гипотезы для дальнейшей группировки и связей между гипотезами.',
      },
    }, withOffset(SLOT_POSITIONS.tag[index], seed, slotIndex++, 10))
    addEdge(nodeId, hypothesisId, 'describes')
  })

  if (tags.length > MAX_TAG_NODES) {
    const hiddenCount = tags.length - MAX_TAG_NODES
    const nodeId = `tag-${hypothesis.id}-more`
    addNode({
      id: nodeId,
      type: 'tag',
      label: `+${hiddenCount} тегов`,
      shortLabel: `+${hiddenCount} тегов`,
      payload: {
        title: `Дополнительные теги (${hiddenCount})`,
        description: tags.slice(MAX_TAG_NODES).join(' • '),
      },
    }, withOffset(SLOT_POSITIONS.tag[4], seed, slotIndex++, 8))
    addEdge(nodeId, hypothesisId, 'describes')
  }

  return {
    nodes,
    edges,
    positions,
    defaultSelection: hypothesisId,
  }
}

function buildAdjacency(edges) {
  const adjacency = new Map()

  edges.forEach((edge) => {
    if (!adjacency.has(edge.source)) adjacency.set(edge.source, new Set())
    if (!adjacency.has(edge.target)) adjacency.set(edge.target, new Set())
    adjacency.get(edge.source).add(edge.target)
    adjacency.get(edge.target).add(edge.source)
  })

  return adjacency
}

function legendItems() {
  return [
    { type: 'hypothesis', label: 'Гипотеза' },
    { type: 'goal', label: 'Цель' },
    { type: 'mechanism', label: 'Механизм' },
    { type: 'validation', label: 'Проверка' },
    { type: 'risk', label: 'Риск' },
    { type: 'evidence', label: 'Основания' },
  ]
}

export default function HypothesisRoadmapModal({
  hypothesis,
  hypothesisRank,
  project,
  retrieved = [],
  onClose,
}) {
  const surfaceRef = useRef(null)
  const [surfaceSize, setSurfaceSize] = useState({ width: 0, height: 0 })
  const [selectedNodeId, setSelectedNodeId] = useState(null)
  const [nodePositions, setNodePositions] = useState({})
  const [view, setView] = useState({ zoom: 1, x: 0, y: 0 })
  const [interaction, setInteraction] = useState(null)

  const graph = useMemo(
    () => buildRoadmapGraph(hypothesis, project, retrieved),
    [hypothesis, project, retrieved],
  )

  const adjacency = useMemo(() => buildAdjacency(graph.edges), [graph.edges])

  const defaultZoom = useMemo(() => {
    if (!surfaceSize.width || !surfaceSize.height) return 0.82
    return clamp(
      Math.min((surfaceSize.width - 42) / SCENE_WIDTH, (surfaceSize.height - 42) / SCENE_HEIGHT),
      0.62,
      1.04,
    )
  }, [surfaceSize])

  const selectedNode = useMemo(
    () => graph.nodes.find((node) => node.id === selectedNodeId) || graph.nodes[0] || null,
    [graph.nodes, selectedNodeId],
  )

  const selectedNeighbors = useMemo(
    () => adjacency.get(selectedNodeId) || new Set(),
    [adjacency, selectedNodeId],
  )

  const connectedNodes = useMemo(() => {
    if (!selectedNode) return []
    return graph.edges
      .filter((edge) => edge.source === selectedNode.id || edge.target === selectedNode.id)
      .map((edge) => {
        const targetId = edge.source === selectedNode.id ? edge.target : edge.source
        const node = graph.nodes.find((item) => item.id === targetId)
        if (!node) return null
        return {
          edge,
          node,
        }
      })
      .filter(Boolean)
  }, [graph.edges, graph.nodes, selectedNode])

  useEffect(() => {
    setSelectedNodeId(graph.defaultSelection)
    setNodePositions(graph.positions)
    setView({ zoom: 1, x: 0, y: 0 })
    setInteraction(null)
  }, [graph])

  useEffect(() => {
    const element = surfaceRef.current
    if (!element || typeof ResizeObserver === 'undefined') return undefined

    const updateSize = () => {
      setSurfaceSize({
        width: element.clientWidth,
        height: element.clientHeight,
      })
    }

    updateSize()
    const observer = new ResizeObserver(updateSize)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!defaultZoom) return
    setView((current) => {
      if (current.zoom !== 1 || current.x !== 0 || current.y !== 0) return current
      return {
        zoom: defaultZoom,
        x: 0,
        y: 0,
      }
    })
  }, [defaultZoom])

  useEffect(() => {
    if (!interaction) return undefined

    const handlePointerMove = (event) => {
      const deltaX = event.clientX - interaction.originX
      const deltaY = event.clientY - interaction.originY

      if (interaction.kind === 'pan') {
        setView({
          zoom: interaction.startView.zoom,
          x: interaction.startView.x + deltaX,
          y: interaction.startView.y + deltaY,
        })
        return
      }

      if (interaction.kind === 'node') {
        const divisor = Math.max(interaction.zoom, 0.35)
        setNodePositions((current) => ({
          ...current,
          [interaction.nodeId]: {
            x: clamp(interaction.startPosition.x + deltaX / divisor, 76, SCENE_WIDTH - 76),
            y: clamp(interaction.startPosition.y + deltaY / divisor, 72, SCENE_HEIGHT - 92),
          },
        }))
      }
    }

    const handlePointerUp = () => {
      setInteraction(null)
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp)
    return () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
    }
  }, [interaction])

  const handleFitToScreen = () => {
    setView({
      zoom: defaultZoom,
      x: 0,
      y: 0,
    })
  }

  const handleCenterOnHypothesis = () => {
    setSelectedNodeId(graph.defaultSelection)
    setView((current) => ({
      ...current,
      x: 0,
      y: 0,
    }))
  }

  const handleResetLayout = () => {
    setNodePositions(graph.positions)
    setSelectedNodeId(graph.defaultSelection)
    setInteraction(null)
    handleFitToScreen()
  }

  const handleWheel = (event) => {
    event.preventDefault()
    const nextZoom = clamp(
      view.zoom + (event.deltaY < 0 ? 0.08 : -0.08),
      Math.max(defaultZoom * 0.9, 0.55),
      1.72,
    )

    setView((current) => ({
      ...current,
      zoom: nextZoom,
    }))
  }

  const handleSurfacePointerDown = (event) => {
    if (event.button !== 0) return
    event.preventDefault()
    setInteraction({
      kind: 'pan',
      originX: event.clientX,
      originY: event.clientY,
      startView: view,
    })
  }

  const handleNodePointerDown = (event, nodeId) => {
    if (event.button !== 0) return
    event.preventDefault()
    event.stopPropagation()
    setSelectedNodeId(nodeId)
    setInteraction({
      kind: 'node',
      nodeId,
      originX: event.clientX,
      originY: event.clientY,
      startPosition: nodePositions[nodeId],
      zoom: view.zoom,
    })
  }

  return (
    <Modal
      title={hypothesisRank ? `Дорожная карта гипотезы #${hypothesisRank}` : 'Дорожная карта гипотезы'}
      onClose={onClose}
      className="modal--roadmap"
      footer={(
        <button className="btn primary" type="button" onClick={onClose}>
          Закрыть
        </button>
      )}
    >
      <div className="roadmap-shell">
        <div className="roadmap-canvas-card">
          <div className="roadmap-toolbar">
            <div className="roadmap-toolbar__copy">
              <strong>Связи внутри гипотезы</strong>
              <span>{graph.nodes.length} узлов • {graph.edges.length} связей</span>
            </div>

            <div className="roadmap-toolbar__actions">
              <button className="btn ghost" type="button" onClick={handleFitToScreen}>
                Уместить
              </button>
              <button className="btn ghost" type="button" onClick={handleCenterOnHypothesis}>
                Центрировать
              </button>
              <button className="btn ghost" type="button" onClick={handleResetLayout}>
                Сбросить layout
              </button>
            </div>
          </div>

          <div className="roadmap-legend">
            {legendItems().map((item) => (
              <span className="roadmap-legend__item" key={item.type}>
                <span className={`roadmap-legend__dot roadmap-legend__dot--${item.type}`} />
                {item.label}
              </span>
            ))}
          </div>

          <div
            ref={surfaceRef}
            className={`roadmap-surface ${interaction ? 'is-dragging' : ''}`}
            onPointerDown={handleSurfacePointerDown}
            onWheel={handleWheel}
          >
            <div
              className="roadmap-scene"
              style={{
                width: `${SCENE_WIDTH}px`,
                height: `${SCENE_HEIGHT}px`,
                transform: `translate(-50%, -50%) translate(${view.x}px, ${view.y}px) scale(${view.zoom})`,
              }}
            >
              <svg className="roadmap-edges" viewBox={`0 0 ${SCENE_WIDTH} ${SCENE_HEIGHT}`} aria-hidden="true">
                {graph.edges.map((edge) => {
                  const source = nodePositions[edge.source]
                  const target = nodePositions[edge.target]
                  if (!source || !target) return null

                  const isActive = !selectedNodeId || edge.source === selectedNodeId || edge.target === selectedNodeId
                  return (
                    <line
                      key={edge.id}
                      className={`roadmap-edge ${isActive ? 'is-active' : 'is-muted'}`}
                      x1={source.x}
                      y1={source.y}
                      x2={target.x}
                      y2={target.y}
                    />
                  )
                })}
              </svg>

              {graph.nodes.map((node) => {
                const position = nodePositions[node.id]
                if (!position) return null

                const isSelected = selectedNodeId === node.id
                const isNeighbor = selectedNeighbors.has(node.id)
                const isFaded = selectedNodeId && !isSelected && !isNeighbor

                return (
                  <button
                    key={node.id}
                    type="button"
                    className={`roadmap-node roadmap-node--${node.type} ${isSelected ? 'is-selected' : ''} ${isFaded ? 'is-faded' : ''}`}
                    style={{ left: `${position.x}px`, top: `${position.y}px` }}
                    onPointerDown={(event) => handleNodePointerDown(event, node.id)}
                    onClick={(event) => {
                      event.stopPropagation()
                      setSelectedNodeId(node.id)
                    }}
                    aria-label={`${TYPE_LABELS[node.type]}: ${node.label}`}
                  >
                    <span className="roadmap-node__orb" />
                    <span className="roadmap-node__label">{node.shortLabel}</span>
                  </button>
                )
              })}
            </div>
          </div>
        </div>

        <aside className="roadmap-sidebar">
          {selectedNode ? (
            <>
              <div className="roadmap-sidebar__top">
                <span className={`roadmap-sidebar__badge roadmap-sidebar__badge--${selectedNode.type}`}>
                  {TYPE_LABELS[selectedNode.type]}
                </span>
                {selectedNode.payload?.score !== null && selectedNode.payload?.score !== undefined && (
                  <span className="roadmap-sidebar__score">{selectedNode.payload.score}</span>
                )}
              </div>

              <div className="roadmap-sidebar__section">
                <h3>{selectedNode.payload?.title || selectedNode.label}</h3>
                <p>{selectedNode.payload?.description || 'Для этого узла пока нет подробного пояснения.'}</p>
              </div>

              {selectedNode.payload?.metric && (
                <div className="roadmap-sidebar__section">
                  <h4>Метрика</h4>
                  <p>{selectedNode.payload.metric}</p>
                </div>
              )}

              {selectedNode.payload?.relevance && (
                <div className="roadmap-sidebar__section">
                  <h4>Почему это важно</h4>
                  <p>{selectedNode.payload.relevance}</p>
                </div>
              )}

              {selectedNode.payload?.tags?.length > 0 && (
                <div className="roadmap-sidebar__section">
                  <h4>Теги</h4>
                  <div className="roadmap-sidebar__tags">
                    {selectedNode.payload.tags.map((tag) => (
                      <span key={tag}>{tag}</span>
                    ))}
                  </div>
                </div>
              )}

              <div className="roadmap-sidebar__section">
                <h4>Связанные узлы</h4>
                {connectedNodes.length > 0 ? (
                  <div className="roadmap-sidebar__links">
                    {connectedNodes.map(({ edge, node }) => (
                      <button
                        key={edge.id}
                        type="button"
                        className="roadmap-sidebar__link"
                        onClick={() => setSelectedNodeId(node.id)}
                      >
                        <strong>{node.label}</strong>
                        <span>{edge.label}</span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="roadmap-sidebar__empty">У этого узла пока нет дополнительных связей первого уровня.</p>
                )}
              </div>
            </>
          ) : (
            <p className="roadmap-sidebar__empty">Выберите узел, чтобы посмотреть детали.</p>
          )}
        </aside>
      </div>
    </Modal>
  )
}
