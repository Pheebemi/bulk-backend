"""Builds the sidebar nav for the server-rendered pages — the Django
equivalent of the old AppShell.tsx navItems arrays."""

_ICONS = {
    'dashboard': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/></svg>',
    'contacts': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    'campaign': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4 20-7z"/></svg>',
    'wallet': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4z"/></svg>',
    'sender': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>',
    'analytics': '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M18.7 8 13 13.7l-3-3L4 16.6"/></svg>',
}

_USER_NAV = [
    ('web-dashboard', 'Dashboard', 'dashboard'),
    ('web-contacts', 'Contacts', 'contacts'),
    ('web-campaigns', 'Campaigns', 'campaign'),
    ('web-templates', 'Templates', 'campaign'),
    ('web-wallet', 'Wallet', 'wallet'),
    ('web-sender-ids', 'Sender IDs', 'sender'),
]


_CONSOLE_NAV = [
    ('console-dashboard', 'Dashboard', 'dashboard'),
    ('console-analytics', 'Analytics', 'analytics'),
    ('console-approvals', 'Sender IDs', 'sender'),
    ('console-campaigns', 'Campaigns', 'campaign'),
    ('console-contacts', 'Contacts', 'contacts'),
    ('console-users', 'Users', 'contacts'),
    ('console-wallets', 'User wallets', 'wallet'),
    ('console-send', 'Send campaign', 'campaign'),
]


def nav(request):
    from django.urls import NoReverseMatch, reverse

    items = []
    in_console = request.path.startswith('/console/')
    for name, label, icon in (_CONSOLE_NAV if in_console else _USER_NAV):
        try:
            url = reverse(name)
        except NoReverseMatch:
            continue  # page not built yet
        items.append({
            'url': url,
            'label': label,
            'icon': _ICONS[icon],
            'active': request.path == url or request.path.startswith(url),
        })
    return {'nav_items': items}


def asset_version(request):
    """Cache-buster for the compiled CSS so a deploy's new styles are never
    paired with a browser's stale copy."""
    import os
    return {'asset_version': (os.environ.get('VERCEL_GIT_COMMIT_SHA') or 'dev')[:8]}
