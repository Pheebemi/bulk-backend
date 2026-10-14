"""Marketing copy for the public landing page (ported from the old
Next.js app/page.tsx)."""

USE_CASES = [  # (title, body, icon svg inner markup)
    ('Promotional SMS', 'Announce sales, drops and offers to a contact group in one send, with the cost shown before you confirm.', '<path d="M3 11v2a1 1 0 0 0 1 1h2l5 4V6L6 10H4a1 1 0 0 0-1 1z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18 6a8.5 8.5 0 0 1 0 12"/>'),
    ('Transactional alerts', 'Order confirmations, payment receipts and dispatch notices triggered from your own systems.', '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>'),
    ('Reminders', 'Appointment, renewal and repayment nudges scheduled against a saved contact group.', '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
    ('Service notifications', 'Downtime notices, delivery updates and account alerts sent to everyone at once.', '<path d="M4 4h16v12H7l-3 3z"/>'),
    ('Customer re-engagement', 'Win-back campaigns to lapsed customers, segmented by the groups you have built.', '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>'),
]

INDUSTRIES = [
    ('Financial services', 'Balance alerts, statements and repayment reminders on the DND route, where delivery is not optional.'),
    ('eCommerce', 'Order confirmations, dispatch notices and campaign blasts to your customer list.'),
    ('Schools & training', 'Fee reminders, results notifications and announcements to parents and students.'),
    ('Healthcare', 'Appointment reminders and follow-up messages that cut no-shows.'),
    ('Logistics', 'Pickup, transit and delivery updates triggered from your dispatch system.'),
    ('Churches & associations', 'Service times, events and dues reminders to your whole register in one send.'),
]

FEATURES = [
    {
        'name': 'Contact groups',
        'image': 'illustrations/contacts.svg',
        'title': 'Your contact list stays in your database',
        'body': 'Upload a CSV or add numbers by hand. Contacts are stored on ReachlySMS and handed to the network only as the recipient list of a send — never copied into a third-party phonebook you cannot clear.',
        'points': ['CSV import with first name, last name and number', 'Unlimited groups per account', 'Remove a contact and it is gone for good'],
    },
    {
        'name': 'DND routing',
        'image': 'illustrations/dnd.svg',
        'title': 'Reach numbers on the DND register',
        'body': 'Most Nigerian numbers sit on the Do-Not-Disturb list, which silently drops ordinary marketing traffic. The DND route carries your message anyway, and we check a number’s status before you send.',
        'points': ['Live DND lookup per number', 'Separate rate so the cost is never a surprise', 'Works across MTN, Airtel, Glo and 9mobile'],
    },
    {
        'name': 'Sender IDs',
        'image': 'illustrations/sender-id.svg',
        'title': 'Your brand name on every message',
        'body': 'Messages arrive from your business name rather than a random number. Request a sender ID from the dashboard and we take it through network approval for you.',
        'points': ['Up to 11 characters', 'Request and track status in one place', 'Multiple sender IDs per account'],
    },
    {
        'name': 'Wallet',
        'image': 'illustrations/wallet.svg',
        'title': 'Pay as you go, no monthly fee',
        'body': 'Fund your wallet by card or transfer and spend it down per message. The exact cost of a campaign is calculated and shown before you confirm the send.',
        'points': ['No subscription or minimum spend', 'Full transaction history', 'Unsent messages are refunded automatically'],
    },
    {
        'name': 'Delivery reports',
        'image': 'illustrations/reports.svg',
        'title': 'See what actually landed',
        'body': 'Every campaign records how many messages were delivered and how many failed, down to the individual recipient, so you are never guessing whether a send worked.',
        'points': ['Per-recipient delivery log', 'Campaign-level delivered and failed counts', 'Partial sends refund the difference'],
    },
]

FAQS = [
    ('What does it cost to send an SMS?', 'You pay per message segment, with a separate rate for the DND route. There is no monthly fee and no minimum spend — you fund a wallet and it is drawn down as you send. Current rates are shown in your dashboard, and a campaign’s exact cost is calculated before you confirm it.'),
    ('What counts as one message?', 'A segment is 160 characters. Messages using certain special characters drop to 70 characters per segment. A longer message is charged as multiple segments, and the total is shown before you send.'),
    ('Can I reach numbers on the DND list?', 'Yes. Nigerian networks block ordinary marketing traffic to numbers on the Do-Not-Disturb register. The DND route delivers to them at a slightly higher per-segment rate, and you can check any number’s DND status from the dashboard first.'),
    ('How long does a sender ID take to approve?', 'Sender IDs are approved by the mobile networks, not by us, and typically take one to two business days. You can request one from the dashboard and track its status there; some applications need supporting business documents.'),
    ('How do I add my contacts?', 'Upload a CSV with phone_number, first_name and last_name columns, or a single column of numbers. You can also add contacts one at a time. Contacts are grouped, and a campaign is sent to a whole group at once.'),
    ('What happens if a send fails partway through?', 'You are only charged for the messages that actually went out. If a campaign stops halfway, the recipients who were never sent to are refunded to your wallet automatically and the campaign is marked as partially delivered.'),
]

CHECKLIST = [
    ('Delivery, not just sending', 'A cheap route that silently drops messages costs more than a reliable one. Ask any provider for delivery rates, not send counts.'),
    ('DND coverage', 'If your provider cannot reach the Do-Not-Disturb register, a large share of Nigerian numbers will never see your message.'),
    ('Transparent per-message pricing', 'You should know the exact cost of a campaign before you confirm it, including how many segments a long message becomes.'),
    ('Refunds on failure', 'Find out what happens when a send fails halfway. You should not pay for messages that were never delivered.'),
    ('Sender ID support', 'Messages from a business name are trusted far more than messages from a number. Check the provider will register one for you.'),
    ('Control of your contact data', 'Know where your customer numbers are stored, and confirm you can delete them.'),
]
