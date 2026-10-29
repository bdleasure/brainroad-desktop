// BrainRoad page for Hermes Desktop: start real work on this computer, connect a phone,
// and see what BrainRoad added. Plain ESM loaded uncompiled by Hermes (no JSX, no bundler).
import {
  Badge,
  Button,
  CopyButton,
  PALETTE_AREA,
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  STATUSBAR_AREAS,
  StatusDot,
  Switch,
  host,
  useValue
} from '@hermes/plugin-sdk'
import { useCallback, useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ROUTE = '/brainroad'
const SOURCE = 'https://github.com/bdleasure/brainroad-desktop'
const SUPPORT = 'support@brainroad.com'

const STARTERS = [
  {
    id: 'fix',
    title: 'Fix something on this computer',
    detail: 'A printer, sound, Wi-Fi, an app, a setting or a slowdown.',
    draft: 'Use brainroad:computer-help. What I was trying to do, and what happened instead: '
  },
  {
    id: 'browser',
    title: 'Get something done in a browser',
    detail: 'Look something up, fill in a form, download or upload a file.',
    draft: 'Use brainroad:browser-work. In the browser, I need to: '
  },
  {
    id: 'code',
    title: 'Work on code',
    detail: 'Fix a bug or add a feature in a project on this computer.',
    draft: 'Use brainroad:code-work. In the project at <folder>, I need: '
  }
]

const CHECK_DRAFT = 'Use brainroad:first-task to check that BrainRoad works on this computer.'

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

// Open a fresh chat and put the request in its composer for the person to finish and send.
async function startChat(text) {
  host.navigate('/')
  host.newChat()
  for (let attempt = 0; attempt < 30; attempt += 1) {
    if (await host.composer.setDraft('new', text)) {
      host.composer.focus('new')

      return
    }
    await sleep(100)
  }
  host.notify({ kind: 'info', message: 'Paste this into a new chat: ' + text })
}

function phoneSummary(status) {
  if (!status) return { tone: 'muted', label: 'Checking…' }
  if (status.pairing && status.pairing.status === 'waiting') return { tone: 'warn', label: 'Waiting for approval' }
  if (!status.paired) return { tone: 'muted', label: 'Phone link off' }
  if (status.setupError) return { tone: 'bad', label: 'Setup needs attention' }
  if (status.restartNeeded) return { tone: 'warn', label: 'Restart needed' }
  if (status.state === 'connected') return { tone: 'good', label: 'Phone link on' }
  if (status.state === 'paused') return { tone: 'muted', label: 'Phone link paused' }
  if (status.state === 'revoked') return { tone: 'bad', label: 'Disconnected by BrainRoad' }
  if (status.state === 'error') return { tone: 'bad', label: 'Phone link problem' }

  return { tone: 'warn', label: 'Connecting…' }
}

function diagnostics(status, model) {
  if (!status) return 'BrainRoad status unavailable.'

  return [
    `BrainRoad plugin ${status.version}`,
    `Hermes ${status.hermes || 'unknown'}`,
    `Computer: ${status.computer.os} ${status.computer.arch}`,
    `Model: ${model || 'not chosen'}`,
    `Phone link: ${phoneSummary(status).label}${status.detail ? ' (' + status.detail + ')' : ''}`
  ].join('\n')
}

function useStatus(ctx) {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      setStatus(await ctx.rest('/status'))
      setError('')
    } catch (err) {
      setError(err && err.message ? err.message : String(err))
    }
  }, [ctx])

  useEffect(() => {
    refresh()
    const stopTimer = ctx.setInterval(refresh, 4000)
    const stopEvents = ctx.onEvent('plugin.brainroad.phone.changed', refresh)

    return () => {
      stopTimer()
      stopEvents()
    }
  }, [ctx, refresh])

  return { status, error, refresh, setStatus }
}

function Section({ title, children }) {
  return jsxs('section', {
    className: 'flex flex-col gap-2 border-t border-(--ui-stroke-secondary) pt-4',
    children: [jsx('h2', { className: 'text-sm font-semibold text-(--ui-text-primary)', children: title }), children]
  })
}

function Text({ children, muted }) {
  return jsx('p', {
    className: 'max-w-[62ch] text-xs leading-5 ' + (muted ? 'text-(--ui-text-tertiary)' : 'text-(--ui-text-secondary)'),
    children
  })
}

function Starters() {
  return jsxs('div', {
    className: 'flex flex-col gap-2',
    children: [
      jsx('div', {
        className: 'grid gap-2 sm:grid-cols-3',
        children: STARTERS.map(starter =>
          jsxs(
            'button',
            {
              type: 'button',
              className:
                'flex min-h-20 flex-col items-start gap-1 rounded-[4px] border border-(--ui-stroke-secondary) p-3 text-left hover:bg-(--chrome-action-hover) focus-visible:outline-2 focus-visible:outline-(--ui-accent)',
              onClick: () => startChat(starter.draft),
              children: [
                jsx('span', { className: 'text-sm font-medium text-(--ui-text-primary)', children: starter.title }),
                jsx('span', { className: 'text-xs text-(--ui-text-tertiary)', children: starter.detail })
              ]
            },
            starter.id
          )
        )
      }),
      jsxs('div', {
        className: 'flex flex-wrap items-center gap-2',
        children: [
          jsx(Button, {
            variant: 'ghost',
            size: 'sm',
            onClick: () => startChat(CHECK_DRAFT),
            children: 'Check that BrainRoad works here'
          }),
          jsx(Text, {
            muted: true,
            children: 'Makes a small local page, uses the browser, and saves a receipt. No accounts or websites.'
          })
        ]
      })
    ]
  })
}

function PhoneLink({ ctx, status, refresh, setStatus }) {
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')

  const act = async (label, path, body) => {
    setBusy(label)
    setMessage('')
    try {
      const next = await ctx.rest(path, { method: 'POST', body: body || {} })
      setStatus(next)
      if (next.pairing && next.pairing.status === 'waiting' && path === '/phone/pair') {
        await ctx.os.openExternal(next.pairing.url)
      }

      return next
    } catch (err) {
      setMessage(err && err.message ? err.message : String(err))
    } finally {
      setBusy('')
      refresh()
    }
  }

  const restart = async () => {
    setBusy('restart')
    setMessage('')
    try {
      await host.restartGateway()
      await ctx.rest('/phone/restarted', { method: 'POST', body: {} })
    } catch (err) {
      setMessage(
        'Hermes could not restart yet' + (err && err.message ? ': ' + err.message : '') + '. Finish any running chat and try again.'
      )
    } finally {
      setBusy('')
      refresh()
    }
  }

  if (!status) return jsx(Text, { muted: true, children: 'Checking this computer…' })

  const summary = phoneSummary(status)
  const pairing = status.pairing
  const children = [
    jsxs('div', {
      className: 'flex items-center gap-2 text-xs text-(--ui-text-secondary)',
      children: [jsx(StatusDot, { tone: summary.tone }), summary.label, status.detail ? ' — ' + status.detail : '']
    })
  ]

  if (!status.paired && pairing && pairing.status === 'waiting') {
    children.push(
      jsx(Text, {
        children: [
          'BrainRoad opened in your web browser. Sign in, check that it shows the code ',
          jsx('strong', { className: 'font-mono text-(--ui-text-primary)', children: pairing.code }),
          ', and approve this computer.'
        ]
      }),
      jsxs('div', {
        className: 'flex flex-wrap gap-2',
        children: [
          jsx(Button, { variant: 'chip', size: 'sm', onClick: () => ctx.os.openExternal(pairing.url), children: 'Open approval page again' }),
          jsx(Button, { variant: 'ghost', size: 'sm', onClick: () => act('cancel', '/phone/pair/cancel'), children: 'Cancel' })
        ]
      })
    )
  } else if (!status.paired) {
    children.push(
      jsx(Text, {
        children:
          'Send this computer jobs and check results from your phone’s browser. Your phone reaches this computer through one outbound connection to BrainRoad; nothing on this computer is opened to the internet. You approve it once with your BrainRoad account.'
      }),
      jsx(Text, {
        muted: true,
        children:
          'BrainRoad relays the connection but does not keep your chats, files or screen. While the link is on, your BrainRoad account and BrainRoad’s service are part of what protects this computer, because Hermes can run commands as you. Your phone shows Hermes on this computer, not the phone’s own apps. The computer must be on, awake and running Hermes.'
      }),
      pairing && pairing.status !== 'waiting'
        ? jsx(Text, { muted: true, children: pairing.error || 'The last approval request ' + pairing.status + '. Start again.' })
        : null,
      jsx('div', {
        children: jsx(Button, {
          size: 'sm',
          disabled: Boolean(busy),
          onClick: () => act('pair', '/phone/pair'),
          children: busy === 'pair' ? 'Starting…' : 'Connect my phone'
        })
      })
    )
  } else {
    if (status.setupError) {
      children.push(
        jsx(Text, { children: status.setupError }),
        jsx('div', {
          children: jsx(Button, {
            size: 'sm',
            disabled: Boolean(busy),
            onClick: () => act('finish', '/phone/finish'),
            children: busy === 'finish' ? 'Working…' : 'Try setup again'
          })
        })
      )
    } else if (status.restartNeeded) {
      children.push(
        jsx(Text, {
          children: 'Hermes needs to restart its background service once to turn on phone access. Running chats are not lost.'
        }),
        jsx('div', {
          children: jsx(Button, {
            size: 'sm',
            disabled: Boolean(busy),
            onClick: restart,
            children: busy === 'restart' ? 'Restarting…' : 'Restart Hermes now'
          })
        })
      )
    } else {
      children.push(
        jsx(Text, {
          children: [
            'On your phone, open ',
            jsx('strong', { className: 'text-(--ui-text-primary)', children: 'app.brainroad.com/computers' }),
            ' and sign in with ',
            status.account || 'your BrainRoad account',
            '. Choose ',
            jsx('strong', { className: 'text-(--ui-text-primary)', children: status.deviceName || 'this computer' }),
            '.'
          ]
        })
      )
    }
    children.push(
      jsxs('label', {
        className: 'flex items-center gap-2 text-xs text-(--ui-text-secondary)',
        children: [
          jsx(Switch, {
            checked: Boolean(status.enabled),
            disabled: Boolean(busy) || status.state === 'revoked',
            onCheckedChange: enabled => act('enabled', '/phone/enabled', { enabled })
          }),
          'Allow phone access now'
        ]
      }),
      jsx(Text, {
        muted: true,
        children: 'Turning this off closes the connection immediately. Your phone keeps nothing that can reopen it.'
      }),
      jsx('div', {
        children: jsx(Button, {
          variant: 'ghost',
          size: 'sm',
          disabled: Boolean(busy),
          onClick: () => act('disconnect', '/phone/disconnect'),
          children: busy === 'disconnect' ? 'Disconnecting…' : 'Disconnect this computer from BrainRoad'
        })
      })
    )
  }
  if (message) children.push(jsx(Text, { children: message }))

  return jsx('div', { className: 'flex flex-col gap-2', children })
}

function Choices({ status }) {
  const model = useValue(host.state.model)

  return jsxs('div', {
    className: 'flex flex-col gap-2',
    children: [
      jsx(Text, {
        children: [
          'Model: ',
          jsx('strong', { className: 'text-(--ui-text-primary)', children: model || 'not chosen yet' }),
          '. You choose it in Hermes Settings → Model: a hosted provider, Nous Portal, or a model running on this computer. Tools run on this computer either way, but a hosted model receives what the agent sends it, including text from your files and web pages.'
        ]
      }),
      jsx(Text, {
        children:
          'BrainRoad added four skills, a short set of working rules, this page, and the optional phone link. It does not change Hermes’ permissions, approvals, model or tools. Remove it any time in Capabilities → Plugins; your chats and files stay.'
      }),
      jsxs(Text, {
        muted: true,
        children: [
          'MIT-licensed source: ',
          jsx('a', { className: 'underline', href: SOURCE, target: '_blank', rel: 'noreferrer', children: SOURCE }),
          status ? ' · Plugin ' + status.version : ''
        ]
      })
    ]
  })
}

function Help({ status }) {
  const model = useValue(host.state.model)

  return jsxs('div', {
    className: 'flex flex-wrap items-center gap-2',
    children: [
      jsx(Text, {
        children: [
          'Stuck on something BrainRoad can’t finish? Email ',
          jsx('a', { className: 'underline', href: 'mailto:' + SUPPORT, children: SUPPORT }),
          '. Include the summary below; leave out passwords and private files.'
        ]
      }),
      jsx(CopyButton, { text: diagnostics(status, model), label: 'Copy summary', showLabel: true })
    ]
  })
}

function BrainRoadPage({ ctx }) {
  const { status, error, refresh, setStatus } = useStatus(ctx)
  const computer = status && status.computer

  return jsx('div', {
    className: 'h-full overflow-y-auto',
    children: jsxs('div', {
      className: 'mx-auto flex max-w-3xl flex-col gap-5 px-5 py-6',
      children: [
        jsxs('header', {
          className: 'flex flex-col gap-1.5',
          children: [
            jsxs('div', {
              className: 'flex items-center gap-2',
              children: [
                jsx('h1', { className: 'text-lg font-semibold text-(--ui-text-primary)', children: 'BrainRoad' }),
                jsx(Badge, { variant: 'outline', children: 'preview' })
              ]
            }),
            jsx(Text, {
              children:
                'Tell this computer what you need done. Hermes does the work in the open, keeps a way back, and shows you what proves it worked. Press Stop in the chat whenever you want to take over.'
            }),
            computer
              ? jsx(Text, {
                  muted: true,
                  children: 'Tools run on ' + computer.name + ' (' + computer.os + ', ' + computer.arch + ').'
                })
              : null,
            error ? jsx(Text, { children: 'BrainRoad’s background part is not running: ' + error + '. Turn the BrainRoad agent plugin on in Capabilities → Plugins.' }) : null
          ]
        }),
        jsx(Section, { title: 'What do you need done?', children: jsx(Starters, {}) }),
        jsx(Section, {
          title: 'Use it from your phone',
          children: jsx(PhoneLink, { ctx, status, refresh, setStatus })
        }),
        jsx(Section, { title: 'Your choices', children: jsx(Choices, { status }) }),
        jsx(Section, { title: 'Need a person?', children: jsx(Help, { status }) })
      ]
    })
  })
}

function PhoneChip({ ctx }) {
  const { status } = useStatus(ctx)
  if (!status || !status.paired) return null
  const summary = phoneSummary(status)

  return jsxs('button', {
    type: 'button',
    className: 'flex items-center gap-1 px-1.5 text-[0.6875rem] text-(--ui-text-tertiary) hover:text-(--ui-text-secondary)',
    title: 'BrainRoad phone link',
    onClick: () => host.navigate(ROUTE),
    children: [jsx(StatusDot, { tone: summary.tone }), summary.label]
  })
}

export default {
  id: 'brainroad',
  name: 'BrainRoad',
  register(ctx) {
    ctx.registerMany([
      { id: 'page', area: ROUTES_AREA, data: { path: ROUTE }, render: () => jsx(BrainRoadPage, { ctx }) },
      { id: 'nav', area: SIDEBAR_NAV_AREA, data: { path: ROUTE, label: 'BrainRoad', codicon: 'tools' } },
      { id: 'phone', area: STATUSBAR_AREAS.right, order: 140, render: () => jsx(PhoneChip, { ctx }) },
      {
        id: 'fix',
        area: PALETTE_AREA,
        data: {
          id: 'brainroad.fix',
          label: 'BrainRoad: Fix something on this computer',
          keywords: ['help', 'repair', 'problem'],
          run: () => startChat(STARTERS[0].draft)
        }
      },
      {
        id: 'open',
        area: PALETTE_AREA,
        data: { id: 'brainroad.open', label: 'BrainRoad: Open', keywords: ['phone'], run: () => host.navigate(ROUTE) }
      }
    ])
  }
}

