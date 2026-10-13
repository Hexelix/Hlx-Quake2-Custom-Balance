#!/usr/bin/env python3
"""Apply custom Quake II ammo, weapon, armor, and permanent Mega Health changes.

Works on the original id Software Quake-2 game source (classic) or the
id Software quake2-rerelease-dll SDK (2023 remaster). Requires pristine source.
No game assets or compiled game DLL are included.
"""

import argparse
import difflib
import re
import sys
from pathlib import Path

# Each requested maximum is an absolute value, not a multiplier.
CAPS = {
    'bullets': (500, 750, 1000),
    'shells': (200, 200, 200),
    'rockets': (100, None, 200),
    'grenades': (100, None, 200),
    'cells': (500, 750, 1000),
    'slugs': (100, 150, 200),
}
INITIAL_CLASSIC = dict(bullets=200, shells=100, rockets=50,
                       grenades=50, cells=200, slugs=50)
INITIAL_REMASTER = dict(bullets=200, shells=100, cells=200)
BANDOLIER_STOCK = dict(bullets=250, shells=150, cells=250, slugs=75)
PACK_STOCK = dict(bullets=300, shells=200, rockets=100,
                  grenades=100, cells=300, slugs=100)

# Actual stock damage arguments from id's source; only these six player weapons.
# Each percentage is applied before Quad / Double Damage multipliers.
WEAPON_DAMAGE = {
    'Weapon_Blaster_Fire': [(15, 50)] ,   # remaster only; classic uses branches
    'Weapon_HyperBlaster_Fire': [(15, 50), (20, 50)],
    'Machinegun_Fire': [(8, 20)],
    'Chaingun_Fire': [(6, 20), (8, 20)],
    'weapon_shotgun_fire': [(4, 20)],
    'weapon_supershotgun_fire': [(6, 20)],
}


def change_number(src, pattern, stock, target, label):
    matches = list(re.finditer(pattern, src, re.MULTILINE))
    if len(matches) != 1:
        raise ValueError(f'{label}: expected 1 occurrence, got {len(matches)}. Check SDK revision / previous mods.')
    m = matches[0]
    value = int(m.group('number'))
    if value != stock:
        raise ValueError(f'{label}: stock value should be {stock}; found {value}. Use pristine sources.')
    start, end = m.span('number')
    return src[:start] + str(target) + src[end:]


def function_segment(src, name, return_type):
    if return_type == 'THINK':
        pat = r'\bTHINK\s*\(\s*' + re.escape(name) + r'\s*\)\s*\('
    else:
        pat = r'\b' + re.escape(return_type) + r'\s+' + re.escape(name) + r'\s*\('
    candidates = []
    for match in re.finditer(pat, src):
        brace = src.find('{', match.end())
        semicolon = src.find(';', match.end())
        if brace >= 0 and (semicolon < 0 or brace < semicolon):
            candidates.append(brace)
    if len(candidates) != 1:
        raise ValueError(f'{name}: expected one definition, found {len(candidates)}')
    # Ignore forward declarations and balance only the function body.
    brace = candidates[0]
    if brace < 0:
        raise ValueError(f'{name}: function body not found')
    depth = 0
    for pos in range(brace, len(src)):
        if src[pos] == '{':
            depth += 1
        elif src[pos] == '}':
            depth -= 1
            if depth == 0:
                return brace, pos + 1
    raise ValueError(f'{name}: unbalanced braces')


def edit_function(src, name, return_type, edit):
    start, end = function_segment(src, name, return_type)
    return src[:start] + edit(src[start:end]) + src[end:]


def edit_initial(src, edition):
    if edition == 'classic':
        for ammo, original in INITIAL_CLASSIC.items():
            pat = rf'\bclient->pers\.max_{ammo}\s*=\s*(?P<number>\d+)\s*;'
            src = change_number(src, pat, original, CAPS[ammo][0], 'initial ' + ammo)
    else:
        for ammo, original in INITIAL_REMASTER.items():
            pat = rf'\bclient->pers\.max_ammo\[\s*AMMO_{ammo.upper()}\s*\]\s*=\s*(?P<number>\d+)\s*;'
            src = change_number(src, pat, original, CAPS[ammo][0], 'initial ' + ammo)
        # The rerelease initializes the other core ammo to 50 using .fill(50).
        # Add targeted overrides. Do NOT change the default for expansion ammo.
        if len(re.findall(r'\bclient->pers\.max_ammo\.fill\(50\)', src)) != 1:
            raise ValueError('Expected exactly one remaster max_ammo.fill(50)')
        marker = re.compile(r'(?P<indent>^[ \t]*)client->pers\.max_ammo\[AMMO_CELLS\] = 500;(?P<newline>\r?\n)', re.MULTILINE)
        matches = list(marker.finditer(src))
        if len(matches) != 1:
            raise ValueError('Unable to insert initial remaster rockets/grenades/slugs after cells')
        m = matches[0]
        indentation, nl = m.group('indent'), m.group('newline')
        addition = ''.join(f'{indentation}client->pers.max_ammo[AMMO_{a.upper()}] = {CAPS[a][0]};{nl}'
                           for a in ('rockets', 'grenades', 'slugs'))
        src = src[:m.end()] + addition + src[m.end():]
    return src


def edit_upgrades(src, edition):
    for fn, stock, capidx in (('Pickup_Bandolier', BANDOLIER_STOCK, 1), ('Pickup_Pack', PACK_STOCK, 2)):
        return_type = 'bool' if edition == 'remaster' else 'qboolean'
        def transform(body):
            for ammo, original in stock.items():
                maximum = CAPS[ammo][capidx]
                if maximum is None:
                    continue
                if edition == 'remaster':
                    pat = (r'\bG_AdjustAmmoCap\(\s*other\s*,\s*AMMO_' + ammo.upper() +
                           r'\s*,\s*(?P<number>\d+)\s*\)')
                    body = change_number(body, pat, original, maximum, f'{fn}: {ammo}')
                else:
                    for operator in ('<', '='):
                        pat = (r'\bother->client->pers\.max_' + ammo + r'\s*' +
                               re.escape(operator) + r'\s*(?P<number>\d+)\s*' +
                               (r';' if operator == '=' else ''))
                        body = change_number(body, pat, original, maximum, f'{fn}: {ammo} {operator}')
            return body
        src = edit_function(src, fn, return_type, transform)
    return src


def edit_armor(src, edition):
    """Double suit armor pickup values and make armor shards worth five points.

    Preserve normal armor caps (50/100/200) and the stock armor protection
    fractions. Only modify the player's Pickup_Armor implementation.
    """
    def transform(body):
        if edition == 'remaster':
            pat = (r'(?P<indent>^[ \t]*)int32_t base_count = ent->count \? ent->count : '
                   r'newinfo \? newinfo->base_count : 0;(?P<nl>\r?\n)')
            matches = list(re.finditer(pat, body, re.MULTILINE))
            if len(matches) != 1:
                raise ValueError('Pickup_Armor: remaster base_count expression not found')
            m = matches[0]
            insertion = f'{m.group("indent")}base_count *= 2;{m.group("nl")}'
            body = body[:m.end()] + insertion + body[m.end():]
        else:
            stock = 'newinfo->base_count'
            num = body.count(stock)
            if num != 3:
                raise ValueError(f'Pickup_Armor: expected 3 classic base_count uses; got {num}')
            body = body.replace(stock, '(newinfo->base_count * 2)')

        jacket = 'IT_ARMOR_JACKET' if edition == 'remaster' else 'jacket_armor_index'
        for label, rx in [
            ('no armor', r'other->client->pers.inventory\[' + jacket +
             r'\]\s*=\s*(?P<number>\d+)\s*;'),
            ('existing armor', r'other->client->pers.inventory\[old_armor_index\]'
             r'\s*\+=\s*(?P<number>\d+)\s*;'),
        ]:
            body = change_number(body, rx, 2, 5, f'Pickup_Armor shard {label}')
        return body
    return edit_function(src, 'Pickup_Armor',
                         'bool' if edition == 'remaster' else 'qboolean',
                         transform)


def edit_machinegun_spread(src):
    """Halve both machinegun bullet spread axes, leaving other guns unchanged."""
    def transform(body):
        pattern = (r'\bDEFAULT_BULLET_HSPREAD\s*,\s*'
                   r'DEFAULT_BULLET_VSPREAD\s*,\s*MOD_MACHINEGUN\b')
        matches = list(re.finditer(pattern, body))
        if len(matches) != 1:
            raise ValueError(
                f'Machinegun_Fire: expected one stock spread call, got {len(matches)}')
        replacement = ('(DEFAULT_BULLET_HSPREAD / 2), '
                       '(DEFAULT_BULLET_VSPREAD / 2), MOD_MACHINEGUN')
        return body[:matches[0].start()] + replacement + body[matches[0].end():]
    return edit_function(src, 'Machinegun_Fire', 'void', transform)


def edit_weapon(src, edition):
    # Multiply base damage by 120/100 or 150/100. Since Quake II damage is
    # integer, round *stochastically* (unbiased over many shots). Each shotgun
    # fires all pellets at one randomly rounded damage per attack. Weapon kick,
    # fire rate, ammo consumption, splash etc. stay unchanged.
    if 'Q2ModScaleDamage' in src:
        raise ValueError('p_weapon is already patched; restore pristine source')
    specs = dict(WEAPON_DAMAGE)
    if edition == 'classic':
        specs['Weapon_Blaster_Fire'] = [(15, 50), (10, 50)]
    for fn, variants in specs.items():
        def transform(body):
            for stock, percent in variants:
                pat = r'\bdamage\s*=\s*(?P<number>' + str(stock) + r')\s*;'
                # Validate stock branch exact uniqueness; for remaster blaster/shotgun/etc
                # the 'int damage = N' initializer also matches this pattern.
                matches = list(re.finditer(pat, body))
                if len(matches) != 1:
                    raise ValueError(f'{fn}: expected one damage={stock} initializer, got {len(matches)}')
                target = f'Q2ModScaleDamage({stock}, {percent})'
                m = matches[0]
                body = body[:m.start('number')] + target + body[m.end('number'):]
            return body
        src = edit_function(src, fn, 'void', transform)
    rand = 'frandom() * 100.0f' if edition == 'remaster' else '(rand() % 100)'
    helper = (
        '// Quake II custom-balance mod: unbiased rounding of integer damage.\n'
        'static int Q2ModScaleDamage(int base, int bonus_percent)\n'
        '{\n'
        '\tint scaled = base * (100 + bonus_percent);\n'
        '\tint whole = scaled / 100;\n'
        '\tint fractional = scaled % 100;\n'
        f'\tif (fractional && ({rand}) < fractional)\n'
        '\t\twhole++;\n'
        '\treturn whole;\n'
        '}\n\n'
    )
    # Insert before the first patched rocket damage call (and subsequent weapons).
    anchor = re.compile(r'^void\s+Weapon_RocketLauncher_Fire\s*\(', re.MULTILINE)
    ms = list(anchor.finditer(src))
    if len(ms) != 1:
        raise ValueError('Could not locate RocketLauncher_Fire definition to insert damage helper')
    src = src[:ms[0].start()] + helper + src[ms[0].start():]
    return edit_explosive_weapons(edit_machinegun_spread(src), edition)


def edit_megahealth_think(src, edition):
    """Stop Mega Health decay while preserving item cleanup/DM respawning."""
    def transform(body):
        start_marker = 'if (self->owner->health > self->owner->max_health'
        end_marker = 'if (!(self->spawnflags & '
        if body.count(start_marker) != 1 or body.count(end_marker) != 1:
            raise ValueError('MegaHealth_think: stock decay/respawn logic not found')
        start, end = body.index(start_marker), body.index(end_marker)
        if end <= start:
            raise ValueError('MegaHealth_think: unexpected source ordering')
        decay = body[start:end]
        if (decay.count('self->owner->health -= 1;') != 1
                or decay.count('self->nextthink = level.time + ') != 1
                or decay.count('return;') != 1
                or decay.count('}') != 1):
            raise ValueError('MegaHealth_think: unexpected stock decay logic')
        # Keep the normal deathmatch item respawn / single-player cleanup.
        return body[:start] + body[end:]
    return edit_function(src, 'MegaHealth_think',
                         'THINK' if edition == 'remaster' else 'void',
                         transform)


def edit_megahealth_player(src):
    """Disable remaster single-player decay, including timers in old saves."""
    def transform(body):
        if (body.count('ent->health--;') != 1
                or body.count('ent->client->pers.megahealth_time -= FRAME_TIME_S;') != 1):
            raise ValueError('P_RunMegaHealth: expected stock single-player decay logic')
        return chr(10).join((
            '{',
            '    // Keep overhealth permanently; clear any timer loaded from a save.',
            '    ent->client->pers.megahealth_time = 0_ms;',
            '}'))
    return edit_function(src, 'P_RunMegaHealth', 'void', transform)


def edit_explosive_weapons(src, edition):
    """Double player grenade radii and increase rocket impact damage 75%."""
    for name, stock in (('weapon_grenade_fire', 125),
                        ('weapon_grenadelauncher_fire', 120)):
        def change(body):
            pat = r'\bradius\s*=\s*(?:\(float\)\s*\()?\s*\(?damage\s*\+\s*40\)?\s*;'
            matches = list(re.finditer(pat, body))
            if len(matches) != 1:
                raise ValueError(f'{name}: expected stock radius calculation')
            m = matches[0]
            return body[:m.start()] + 'radius = (damage + 40) * 2.0f;' + body[m.end():]
        src = edit_function(src, name, 'void', change)
    def rocket(body):
        pat = (r'\bdamage\s*=\s*(?:irandom\(100,\s*120\)|'
               r'100\s*\+\s*\(int\)\s*\(random\(\)\s*\*\s*20\.0\))\s*;')
        m = list(re.finditer(pat, body))
        if len(m) != 1:
            raise ValueError('RocketLauncher: expected stock damage initialization')
        x = m[0]
        return (body[:x.end()] + '\n\tdamage = Q2ModScaleDamage(damage, 75);'
                + body[x.end():])
    return edit_function(src, 'Weapon_RocketLauncher_Fire', 'void', rocket)


def edit_grenade_splash(src, edition):
    """Increase player grenade splash only, not impact or monster attacks."""
    def transform(body):
        if edition == 'remaster':
            old = 'T_RadiusDamage(ent, ent->owner, (float) ent->dmg, ent->enemy, ent->dmg_radius, DAMAGE_NONE, mod);'
            new = ('T_RadiusDamage(ent, ent->owner, '
                   '(float) ent->dmg * (ent->owner->client ? 1.5f : 1.0f), '
                   'ent->enemy, ent->dmg_radius, DAMAGE_NONE, mod);')
        else:
            old = 'T_RadiusDamage(ent, ent->owner, ent->dmg, ent->enemy, ent->dmg_radius, mod);'
            new = ('T_RadiusDamage(ent, ent->owner, '
                   '(int) (ent->dmg * (ent->owner->client ? 1.5f : 1.0f)), '
                   'ent->enemy, ent->dmg_radius, mod);')
        if body.count(old) != 1:
            raise ValueError('Grenade_Explode: expected stock splash damage call')
        return body.replace(old, new)
    return edit_function(src, 'Grenade_Explode',
                         'THINK' if edition == 'remaster' else 'void',
                         transform)


def patch_sources(originals, edition):
    expected = 5 if edition == 'remaster' else 4
    if len(originals) != expected:
        raise ValueError(f'{edition}: expected {expected} source files, got {len(originals)}')
    patched = [
        edit_initial(originals[0], edition),
        edit_megahealth_think(
            edit_armor(edit_upgrades(originals[1], edition), edition), edition),
        edit_weapon(originals[2], edition),
    ]
    if edition == 'remaster':
        patched.append(edit_megahealth_player(originals[3]))
    patched.append(edit_grenade_splash(originals[-1], edition))
    return patched


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='SDK/repository root, rerelease/, or game/ folder')
    parser.add_argument('--edition', choices=('remaster', 'classic'), default='remaster')
    parser.add_argument('--dry-run', action='store_true', help='Print a diff without modifying files')
    args = parser.parse_args(argv)
    suffix = 'rerelease' if args.edition == 'remaster' else 'game'
    ext = '.cpp' if args.edition == 'remaster' else '.c'
    root = args.source
    if not (root / ('p_client' + ext)).is_file():
        root = root / suffix
    names = ('p_client', 'g_items', 'p_weapon')
    if args.edition == 'remaster':
        names += ('p_view',)
    names += ('g_weapon',)
    paths = [root / (name + ext) for name in names]
    for path in paths:
        if not path.is_file():
            parser.error(f'Source not found: {path}')

    try:
        originals = [p.read_bytes() for p in paths]
        edited_text = patch_sources([b.decode('utf-8') for b in originals], args.edition)
        edited = [s.encode('utf-8') for s in edited_text]
    except (UnicodeDecodeError, ValueError) as exc:
        parser.error(str(exc))
    for path, a, b in zip(paths, originals, edited):
        old, new = a.decode('utf-8'), b.decode('utf-8')
        print('\n' + ''.join(difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile=str(path) + ' (stock)', tofile=str(path) + ' (modded)', n=2)))
    if args.dry_run:
        print('\nDRY RUN — no files changed.')
        return 0
    backup_paths = [Path(str(p) + '.balance-original.bak') for p in paths]
    if any(p.exists() for p in backup_paths):
        parser.error('Backup already exists. Use a clean SDK copy; no source files changed.')
    try:
        for path, raw in zip(backup_paths, originals):
            path.write_bytes(raw)
        for path, raw in zip(paths, edited):
            path.write_bytes(raw)
    except OSError:
        for path, raw in zip(paths, originals):
            path.write_bytes(raw)
        raise
    print(f'\nPatched all {len(paths)} source files. Original versions saved as *.balance-original.bak.')
    print('Compile your game module using the source SDK / engine build system.')
    return 0


if __name__ == '__main__':
    sys.exit(main())