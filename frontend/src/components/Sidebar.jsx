/**
 * Sidebar.jsx
 * Left navigation sidebar with active link highlighting.
 */

import React from 'react'

const NAV_ITEMS = [
    {
        id: 'dashboard',
        label: 'Dashboard',
        icon: (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="w-5 h-5">
                <rect x="3" y="3" width="7" height="7" rx="1" />
                <rect x="14" y="3" width="7" height="7" rx="1" />
                <rect x="3" y="14" width="7" height="7" rx="1" />
                <rect x="14" y="14" width="7" height="7" rx="1" />
            </svg>
        ),
    },
    {
        id: 'alerts',
        label: 'Alerts',
        icon: (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="w-5 h-5">
                <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
        ),
    },
    {
        id: 'diagnostics',
        label: 'Diagnostics',
        icon: (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="w-5 h-5">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
            </svg>
        ),
    },
    {
        id: 'ai',
        label: 'AI Analysis',
        icon: (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="w-5 h-5">
                <circle cx="12" cy="12" r="10" />
                <path d="M12 8v4l3 3" />
            </svg>
        ),
    },
]

export default function Sidebar({ activePage, onNavigate, serialStatus }) {
    return (
        <aside className="flex flex-col w-56 min-h-screen bg-surface-raised border-r border-surface-border shrink-0">
            {/* Logo / Brand */}
            <div className="flex items-center gap-3 px-5 py-5 border-b border-surface-border">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-blue/20 text-accent-blue">
                    <svg viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
                        <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
                    </svg>
                </div>
                <div>
                    <div className="text-sm font-semibold text-white leading-tight">Industrial</div>
                    <div className="text-xs text-gray-500 leading-tight">Monitor v1.0</div>
                </div>
            </div>

            {/* Navigation */}
            <nav className="flex-1 py-4 px-2">
                <p className="px-3 mb-2 text-[10px] uppercase tracking-widest text-gray-500 font-semibold">
                    Navigation
                </p>
                <ul className="space-y-0.5">
                    {NAV_ITEMS.map((item) => {
                        const isActive = activePage === item.id
                        return (
                            <li key={item.id}>
                                <button
                                    onClick={() => onNavigate(item.id)}
                                    className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${isActive
                                        ? 'bg-accent-blue/15 text-accent-blue'
                                        : 'text-gray-400 hover:bg-surface-elevated hover:text-white'
                                        }`}
                                >
                                    {item.icon}
                                    {item.label}
                                </button>
                            </li>
                        )
                    })}
                </ul>
            </nav>

            {/* Footer: always LIVE badge */}
            <div className="px-4 py-4 border-t border-surface-border space-y-2">
                <div className="flex items-center gap-2 text-xs">
                    <span className="h-2 w-2 rounded-full bg-accent-green animate-pulse" />
                    <span className="text-accent-green font-semibold">LIVE</span>
                </div>
                {serialStatus?.port && (
                    <div className="text-[10px] font-mono text-gray-600 truncate">
                        {serialStatus.port} @ {serialStatus.baud}
                    </div>
                )}
            </div>
        </aside>
    )
}
