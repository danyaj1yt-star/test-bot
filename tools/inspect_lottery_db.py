import sqlite3
import os
import shutil
import datetime

BASE = os.path.dirname(os.path.dirname(__file__))
DB_FOLDER = os.path.join(BASE, 'database')
MSG_DB = os.path.join(DB_FOLDER, 'messages.db')
REF_DB = os.path.join(DB_FOLDER, 'referral_bot.db')

print('DB folder:', DB_FOLDER)
for p in (MSG_DB, REF_DB):
    print('\nChecking', p)
    if os.path.exists(p):
        st = os.stat(p)
        print(' - exists, size=%d bytes, mtime=%s' % (st.st_size, datetime.datetime.fromtimestamp(st.st_mtime)))
    else:
        print(' - MISSING')

# Make timestamped backups
ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
backups = []
for p in (MSG_DB, REF_DB):
    if os.path.exists(p):
        dest = p + f'.bak_{ts}'
        try:
            shutil.copy2(p, dest)
            backups.append(dest)
            print('Backed up', p, '->', dest)
        except Exception as e:
            print('Failed to backup', p, e)

# Inspect messages DB
if os.path.exists(MSG_DB):
    try:
        conn = sqlite3.connect(MSG_DB)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        print('\nTables in messages.db:', tables)

        if 'lottery_tickets' in tables:
            cur.execute('SELECT COUNT(*) FROM lottery_tickets')
            cnt = cur.fetchone()[0]
            print('lottery_tickets count=', cnt)
            cur.execute('SELECT user_id, username, purchase_date FROM lottery_tickets ORDER BY purchase_date DESC LIMIT 20')
            recent = cur.fetchall()
            print('last 20 tickets:')
            for r in recent:
                print(' ', r)
            # aggregate top holders
            cur.execute('SELECT user_id, username, COUNT(*) as cnt FROM lottery_tickets GROUP BY user_id, username ORDER BY cnt DESC LIMIT 20')
            agg = cur.fetchall()
            print('top ticket holders (today total):')
            for r in agg:
                print(' ', r)
        else:
            print('No lottery_tickets table found')

        if 'lottery_draws' in tables:
            cur.execute('SELECT COUNT(*) FROM lottery_draws')
            cnt = cur.fetchone()[0]
            print('lottery_draws count=', cnt)
            cur.execute('SELECT draw_date, winner_user_id, winner_username, total_tickets, prize_amount, status FROM lottery_draws ORDER BY draw_date DESC LIMIT 10')
            draws = cur.fetchall()
            print('last draws:')
            for d in draws:
                print(' ', d)
        else:
            print('No lottery_draws table found')

        conn.close()
    except Exception as e:
        print('Error querying messages.db:', e)

# Inspect referral DB for balances top10
if os.path.exists(REF_DB):
    try:
        conn = sqlite3.connect(REF_DB)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        print('\nTables in referral_bot.db:', tables)
        if 'users' in tables:
            cur.execute('SELECT COUNT(*) FROM users')
            print('users count=', cur.fetchone()[0])
            cur.execute('SELECT user_id, username, dan FROM users ORDER BY dan DESC LIMIT 20')
            top = cur.fetchall()
            print('top balances:')
            for t in top:
                print(' ', t)
        conn.close()
    except Exception as e:
        print('Error querying referral_bot.db:', e)

print('\nBackups created:', backups)
print('Done')
