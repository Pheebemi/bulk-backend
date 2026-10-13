"""Marketing copy for the public landing page (ported from the old
Next.js app/page.tsx)."""

USE_CASES = [
    ('Promotional SMS', 'Announce sales, drops and offers to a contact group in one send, with the cost shown before you confirm.'),
    ('OTP & 2FA', 'One-time codes over the DND route, so verification messages reach customers who have blocked marketing traffic.'),
    ('Transactional alerts', 'Order confirmations, payment receipts and dispatch notices triggered from your own systems.'),
    ('Reminders', 'Appointment, renewal and repayment nudges scheduled against a saved contact group.'),
    ('Service notifications', 'Downtime notices, delivery updates and account alerts sent to everyone at once.'),
    ('Customer re-engagement', 'Win-back campaigns to lapsed customers, segmented by the groups you have built.'),
]

INDUSTRIES = [
    ('Financial services', 'OTPs, balance alerts and repayment reminders on the DND route, where delivery is not optional.'),
    ('eCommerce', 'Order confirmations, dispatch notices and campaign blasts to your customer list.'),
    ('Schools & training', 'Fee reminders, results notifications and announcements to parents and students.'),
    ('Healthcare', 'Appointment reminders and follow-up messages that cut no-shows.'),
    ('Logistics', 'Pickup, transit and delivery updates triggered from your dispatch system.'),
    ('Churches & associations', 'Service times, events and dues reminders to your whole register in one send.'),
]

FEATURES = [
    {
        'name': 'Contact groups',
        'title': 'Your contact list stays in your database',
        'body': 'Upload a CSV or add numbers by hand. Contacts are stored on Reachly and handed to the network only as the recipient list of a send — never copied into a third-party phonebook you cannot clear.',
        'points': ['CSV import with first name, last name and number', 'Unlimited groups per account', 'Remove a contact and it is gone for good'],
    },
    {
        'name': 'DND routing',
        'title': 'Reach numbers on the DND register',
        'body': 'Most Nigerian numbers sit on the Do-Not-Disturb list, which silently drops ordinary marketing traffic. The DND route carries your message anyway, and we check a number’s status before you send.',
        'points': ['Live DND lookup per number', 'Separate rate so the cost is never a surprise', 'Works across MTN, Airtel, Glo and 9mobile'],
    },
    {
        'name': 'Sender IDs',
        'title': 'Your brand name on every message',
        'body': 'Messages arrive from your business name rather than a random number. Request a sender ID from the dashboard and we take it through network approval for you.',
        'points': ['Up to 11 characters', 'Request and track status in one place', 'Multiple sender IDs per account'],
    },
    {
        'name': 'Wallet',
        'title': 'Pay as you go, no monthly fee',
        'body': 'Fund your wallet by card or transfer and spend it down per message. The exact cost of a campaign is calculated and shown before you confirm the send.',
        'points': ['No subscription or minimum spend', 'Full transaction history', 'Unsent messages are refunded automatically'],
    },
    {
        'name': 'Delivery reports',
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
