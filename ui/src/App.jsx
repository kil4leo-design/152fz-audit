import { useState } from 'react'

const API_URL = 'http://localhost:8000'

const SEVERITY_LABEL = {
  critical: 'Критическое',
  warning: 'Предупреждение',
  info: 'Информация',
}

const SEVERITY_COLOR = {
  critical: '#dc2626',
  warning: '#d97706',
  info: '#2563eb',
}

const STATUS_META = {
  violations_found:    { text: 'Найдены нарушения',       color: '#dc2626', bg: '#fef2f2' },
  recommendations_only:{ text: 'Только рекомендации',     color: '#d97706', bg: '#fffbeb' },
  compliant:           { text: 'Нарушений не найдено',    color: '#16a34a', bg: '#f0fdf4' },
  waf_blocked:         { text: 'Сайт заблокировал сканер', color: '#7c3aed', bg: '#f5f3ff' },
}

function Badge({ severity }) {
  const color = SEVERITY_COLOR[severity] || '#6b7280'
  return (
    <span style={{
      background: color, color: '#fff',
      borderRadius: 4, padding: '2px 8px',
      fontSize: 12, fontWeight: 600, flexShrink: 0,
    }}>
      {SEVERITY_LABEL[severity] || severity}
    </span>
  )
}

function FineTable({ fine }) {
  const a = fine.amounts
  const rows = [
    a.legal_entity  && ['Юридическое лицо', a.legal_entity],
    a.official      && ['Должностное лицо',  a.official],
    a.entrepreneur  && ['ИП',                a.entrepreneur],
    a.individual    && ['Физическое лицо',   a.individual],
  ].filter(Boolean)

  if (!rows.length) return null
  return (
    <div style={{ background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: 6, padding: '8px 12px', marginBottom: 12, fontSize: 13 }}>
      <strong>Штраф ({fine.article}):</strong>
      <table style={{ marginTop: 6, borderCollapse: 'collapse', width: '100%' }}>
        <tbody>
          {rows.map(([label, amount]) => (
            <tr key={label}>
              <td style={{ color: '#555', paddingRight: 12, paddingBottom: 2, whiteSpace: 'nowrap' }}>{label}</td>
              <td style={{ fontWeight: 600 }}>{amount}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PassedCard({ p }) {
  return (
    <div style={{
      border: '2px solid #16a34a', borderRadius: 8, padding: '12px 16px',
      marginBottom: 8, display: 'flex', alignItems: 'center', gap: 12,
    }}>
      <span style={{
        background: '#16a34a', color: '#fff',
        borderRadius: 4, padding: '2px 8px',
        fontSize: 12, fontWeight: 600, flexShrink: 0,
      }}>
        ✓ Пройдено
      </span>
      <div>
        <strong style={{ fontSize: 14 }}>{p.id}: {p.name}</strong>
        <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>
          {p.legal_ref.law}, {p.legal_ref.article}
        </div>
      </div>
    </div>
  )
}

function ViolationCard({ v, isRecommendation }) {
  const borderColor = isRecommendation ? SEVERITY_COLOR.warning : (SEVERITY_COLOR[v.severity] || '#6b7280')
  return (
    <div style={{ border: `2px solid ${borderColor}`, borderRadius: 8, padding: 16, marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        <Badge severity={isRecommendation ? 'warning' : v.severity} />
        <strong style={{ fontSize: 15 }}>{v.id}: {v.name}</strong>
      </div>

      <div style={{ fontSize: 13, color: '#555', marginBottom: 10 }}>
        {v.legal_ref.law}, {v.legal_ref.article}
      </div>

      {!isRecommendation && v.fine && <FineTable fine={v.fine} />}

      <div>
        <strong style={{ fontSize: 13 }}>Как исправить:</strong>
        <p style={{ fontSize: 13, margin: '4px 0 8px', color: '#374151' }}>{v.fix.summary}</p>
        <ol style={{ margin: 0, paddingLeft: 20 }}>
          {v.fix.steps.map((step, i) => (
            <li key={i} style={{ fontSize: 13, marginBottom: 4, color: '#374151' }}>{step}</li>
          ))}
        </ol>
      </div>
    </div>
  )
}

export default function App() {
  const [url, setUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  async function handleScan(e) {
    e.preventDefault()
    setLoading(true)
    setResult(null)
    setError(null)

    try {
      const resp = await fetch(`${API_URL}/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      })

      if (resp.status === 403) {
        setError('robots.txt этого сайта запрещает автоматическое сканирование.')
        return
      }
      if (resp.status === 422) {
        setError('Неверный формат URL. Введите полный адрес: https://example.com')
        return
      }
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}))
        setError(data.detail || `Ошибка сервера: ${resp.status}`)
        return
      }

      setResult(await resp.json())
    } catch {
      setError('Не удалось подключиться к серверу. Убедитесь, что API запущен: uvicorn api.main:app --reload')
    } finally {
      setLoading(false)
    }
  }

  const statusMeta = result ? (STATUS_META[result.summary?.status] || { text: result.summary?.status, color: '#333', bg: '#f9f9f9' }) : null

  return (
    <div style={{ maxWidth: 760, margin: '0 auto', padding: '32px 16px', fontFamily: 'system-ui, -apple-system, sans-serif' }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4, color: '#111' }}>
        Проверка сайта — 152-ФЗ
      </h1>
      <p style={{ color: '#6b7280', marginBottom: 28, fontSize: 14, lineHeight: 1.5 }}>
        Автоматическая проверка публичной части сайта на соответствие требованиям<br />
        ФЗ «О персональных данных» (152-ФЗ, РФ)
      </p>

      <form onSubmit={handleScan} style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
        <input
          type="url"
          value={url}
          onChange={e => setUrl(e.target.value)}
          placeholder="https://example.com"
          required
          disabled={loading}
          style={{
            flex: 1, padding: '10px 14px', fontSize: 15,
            border: '1.5px solid #d1d5db', borderRadius: 6,
            outline: 'none', color: '#111',
          }}
        />
        <button
          type="submit"
          disabled={loading}
          style={{
            padding: '10px 22px', fontSize: 15, fontWeight: 600,
            background: loading ? '#9ca3af' : '#2563eb',
            color: '#fff', border: 'none', borderRadius: 6,
            cursor: loading ? 'not-allowed' : 'pointer',
            whiteSpace: 'nowrap', transition: 'background 0.15s',
          }}
        >
          {loading ? 'Проверяем...' : 'Проверить'}
        </button>
      </form>

      {loading && (
        <div style={{ textAlign: 'center', color: '#6b7280', fontSize: 14, padding: '24px 0' }}>
          Загружаем страницу и анализируем... Это может занять 30–60 секунд.
        </div>
      )}

      {error && (
        <div style={{
          background: '#fef2f2', border: '1px solid #fca5a5',
          borderRadius: 6, padding: '10px 14px',
          marginBottom: 16, color: '#991b1b', fontSize: 14,
        }}>
          {error}
        </div>
      )}

      {result && statusMeta && (
        <div>
          {result.waf_blocked && (
            <div style={{ marginBottom: 20 }}>
              <div style={{
                background: '#f5f3ff', border: '1.5px solid #7c3aed',
                borderRadius: 8, padding: '14px 16px', marginBottom: 12,
                fontSize: 14, color: '#4c1d95',
              }}>
                <strong>Сканер заблокирован защитой сайта (WAF)</strong>
                <p style={{ margin: '8px 0 4px', fontSize: 13, color: '#5b21b6' }}>
                  Сайт использует систему защиты от автоматических запросов (DDoS-Guard, Cloudflare
                  и аналоги). Сканер получил страницу-заглушку, а не реальный сайт.
                  Проверить нарушения 152-ФЗ невозможно — анализ не проводился.
                </p>
                <p style={{ margin: 0, fontSize: 13, color: '#5b21b6' }}>
                  <strong>Что делать:</strong> запустите сканер с IP-адреса самого сайта
                  (с хостингового сервера), либо обратитесь к владельцу сайта.
                </p>
              </div>
              {result.blocked_excerpt && (
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#6b7280', marginBottom: 6 }}>
                    Что увидел сканер вместо сайта:
                  </div>
                  <pre style={{
                    background: '#f8fafc', border: '1px solid #e2e8f0',
                    borderRadius: 6, padding: '12px 14px',
                    fontSize: 12, color: '#374151', whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word', maxHeight: 300, overflowY: 'auto',
                    margin: 0,
                  }}>
                    {result.blocked_excerpt}
                  </pre>
                </div>
              )}
            </div>
          )}
          {result.robots_warning && !result.waf_blocked && (
            <div style={{
              background: '#eff6ff', border: '1px solid #93c5fd',
              borderRadius: 6, padding: '10px 14px',
              marginBottom: 14, fontSize: 13, color: '#1e40af',
            }}>
              <strong>Информация:</strong> robots.txt этого сайта ограничивает автоматический
              доступ. Убедитесь, что вы имеете право на проверку данного сайта.
              Результаты проверки действительны.
            </div>
          )}
          <div style={{
            background: statusMeta.bg,
            border: `1.5px solid ${statusMeta.color}`,
            borderRadius: 8, padding: '12px 16px',
            marginBottom: 20, display: 'flex',
            alignItems: 'center', gap: 16, flexWrap: 'wrap',
          }}>
            <span style={{ color: statusMeta.color, fontWeight: 700, fontSize: 16 }}>
              {statusMeta.text}
            </span>
            <span style={{ fontSize: 13, color: '#6b7280' }}>
              {result.url}
            </span>
            {result.summary.violations_count > 0 && (
              <span style={{ fontSize: 13, color: '#6b7280' }}>
                Нарушений: <strong>{result.summary.violations_count}</strong>
              </span>
            )}
            {result.summary.recommendations_count > 0 && (
              <span style={{ fontSize: 13, color: '#6b7280' }}>
                Рекомендаций: <strong>{result.summary.recommendations_count}</strong>
              </span>
            )}
            {result.summary.passed_count > 0 && (
              <span style={{ fontSize: 13, color: '#6b7280' }}>
                Пройдено: <strong style={{ color: '#16a34a' }}>{result.summary.passed_count}</strong>
              </span>
            )}
          </div>

          {!result.waf_blocked && result.violations.length > 0 && (
            <section style={{ marginBottom: 28 }}>
              <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 12, color: '#dc2626' }}>
                Нарушения ({result.violations.length})
              </h2>
              {result.violations.map((v, i) => (
                <ViolationCard key={i} v={v} isRecommendation={false} />
              ))}
            </section>
          )}

          {!result.waf_blocked && result.recommendations.length > 0 && (
            <section style={{ marginBottom: 28 }}>
              <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 12, color: '#d97706' }}>
                Рекомендации ({result.recommendations.length})
              </h2>
              <p style={{ fontSize: 13, color: '#6b7280', marginBottom: 10 }}>
                Ситуации, которые юридически неоднозначны и требуют уточнения у специалиста.
              </p>
              {result.recommendations.map((v, i) => (
                <ViolationCard key={i} v={v} isRecommendation={true} />
              ))}
            </section>
          )}

          {!result.waf_blocked && result.passed && result.passed.length > 0 && (
            <section style={{ marginBottom: 28 }}>
              <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 12, color: '#16a34a' }}>
                Пройденные проверки ({result.passed.length})
              </h2>
              {result.passed.map((p, i) => (
                <PassedCard key={i} p={p} />
              ))}
            </section>
          )}

          {!result.waf_blocked && result.summary.status === 'compliant' && (
            <div style={{
              background: '#f0fdf4', border: '1px solid #86efac',
              borderRadius: 8, padding: 16, marginBottom: 20, fontSize: 14, color: '#166534',
            }}>
              Автоматическая проверка не выявила нарушений по проверяемым критериям.
            </div>
          )}

          <div style={{
            background: '#f8fafc', border: '1px solid #e2e8f0',
            borderRadius: 6, padding: '10px 14px',
            fontSize: 12, color: '#64748b', lineHeight: 1.6,
          }}>
            {result.disclaimer}
          </div>
        </div>
      )}
    </div>
  )
}
