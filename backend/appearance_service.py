"""Account-scoped visual preferences. No CV or notification settings are changed."""
import json
from backend.database import get_db_connection

THEMES = {'plum': 'Royal Plum', 'lavender': 'Lavender Bloom', 'blue': 'Atlas Blue'}
AVATARS = {'lavender': 'Lavender avatar', 'blue': 'Blue avatar', 'plum': 'Plum avatar'}
DEFAULTS = {'theme': 'plum', 'mode': 'light', 'avatar': 'auto'}


def validate_appearance(values):
    result = {key: values.get(key, default) for key, default in DEFAULTS.items()}
    if result['theme'] not in THEMES or result['mode'] not in {'light','dark','system'} or result['avatar'] not in {*AVATARS,'auto','photo'}:
        raise ValueError('Choose a valid avatar, theme and display mode.')
    return result


def get_appearance(user_id):
    if not user_id:
        return dict(DEFAULTS)
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM user_settings WHERE user_id=?',(user_id,)).fetchone()
        raw = dict(row).get('appearance_json', '{}') if row else '{}'
        return validate_appearance(json.loads(raw))
    except (ValueError,TypeError,AttributeError):
        return dict(DEFAULTS)
    finally:
        conn.close()


def save_appearance(user_id, values):
    value = validate_appearance(values)
    conn = get_db_connection()
    try:
        row=conn.execute('SELECT appearance_json FROM user_settings WHERE user_id=?',(user_id,)).fetchone()
        try:stored=json.loads(row['appearance_json']) if row else {}
        except (ValueError,TypeError):stored={}
        if not isinstance(stored,dict):stored={}
        stored.update(value)
        conn.execute("""INSERT INTO user_settings(user_id,appearance_json) VALUES (?,?)
            ON CONFLICT(user_id) DO UPDATE SET appearance_json=excluded.appearance_json,
            updated_at=CURRENT_TIMESTAMP""",(user_id,json.dumps(stored)))
        conn.commit()
    finally:
        conn.close()
    return value
