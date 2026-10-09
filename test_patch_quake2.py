"""Offline regression tests against representative official SDK source snippets."""
import tempfile
import unittest
from pathlib import Path
from patch_quake2 import (CAPS, INITIAL_CLASSIC, INITIAL_REMASTER,
                          BANDOLIER_STOCK, PACK_STOCK, patch_sources, main)


def fixture_client(edition):
    if edition == 'classic':
        return ('void InitClientPersistant (gclient_t *client) {\n' +
                '\n'.join(f' client->pers.max_{ammo} = {value};' for ammo, value in INITIAL_CLASSIC.items()) +
                '\n}\n')
    return ('void InitClientPersistant(edict_t *ent, gclient_t *client) {\n'
            '    if (!taken_loadout) {\n'
            '        client->pers.max_ammo.fill(50);\n' +
            ''.join(f'        client->pers.max_ammo[AMMO_{ammo.upper()}] = {v};\n' for ammo, v in INITIAL_REMASTER.items()) +
            '        client->pers.max_ammo[AMMO_TRAP] = 5;\n'
            '        client->pers.max_ammo[AMMO_FLECHETTES] = 200;\n'
            '        client->pers.max_ammo[AMMO_DISRUPTOR] = 12;\n'
            '        client->pers.max_ammo[AMMO_TESLA] = 5;\n    }\n}\n')



def fixture_armor(edition):
    if edition == 'remaster':
        return (
            'bool Pickup_Armor(edict_t *ent, edict_t *other) {\n'
            ' const gitem_armor_t *newinfo = ent->item->armor_info;\n'
            ' int32_t base_count = ent->count ? ent->count : newinfo ? newinfo->base_count : 0;\n'
            ' if (ent->item->id == IT_ARMOR_SHARD) {\n'
            '  if (!old_armor_index) other->client->pers.inventory[IT_ARMOR_JACKET] = 2;\n'
            '  else other->client->pers.inventory[old_armor_index] += 2;\n'
            ' } else if (!old_armor_index) other->client->pers.inventory[ent->item->id] = base_count;\n'
            '}\n')
    return (
        'qboolean Pickup_Armor (edict_t *ent, edict_t *other) {\n'
        ' gitem_armor_t *newinfo = (gitem_armor_t *)ent->item->info;\n'
        ' if (ent->item->tag == ARMOR_SHARD) {\n'
        '  if (!old_armor_index) other->client->pers.inventory[jacket_armor_index] = 2;\n'
        '  else other->client->pers.inventory[old_armor_index] += 2;\n'
        ' } else if (!old_armor_index) other->client->pers.inventory[ITEM_INDEX(ent->item)] = newinfo->base_count;\n'
        ' else { newcount = newinfo->base_count + salvagecount; '
        ' salvagecount = salvage * newinfo->base_count; }\n'
        '}\n')


def fixture_upgrade(edition):
    output = ''
    for func, values in (('Pickup_Bandolier', BANDOLIER_STOCK), ('Pickup_Pack', PACK_STOCK)):
        output += ('bool' if edition == 'remaster' else 'qboolean') + f' {func}(edict_t *ent, edict_t *other) {{\n'
        for ammo, original in values.items():
            if edition == 'remaster':
                output += f' G_AdjustAmmoCap(other, AMMO_{ammo.upper()}, {original});\n'
            else:
                output += f' if (other->client->pers.max_{ammo} < {original})\n'
                output += f'  other->client->pers.max_{ammo} = {original};\n'
        if edition == 'remaster':
            output += ' G_AdjustAmmoCap(other, AMMO_MAGSLUG, 75);\n' if func == 'Pickup_Bandolier' else ' G_AdjustAmmoCap(other, AMMO_MAGSLUG, 100);\n'
        output += '}\n'
    return output + fixture_armor(edition)


def fixture_weapon(edition):
    if edition == 'remaster':
        blaster = 'int damage = 15;'
    else:
        blaster = 'int damage;\n if (deathmatch->value) damage = 15; else damage = 10;'
    return '\n'.join([
        'void Blaster_Fire(edict_t *ent) { /* projectiles */ }',
        f'void Weapon_Blaster_Fire(edict_t *ent) {{ {blaster} }}',
        'void Weapon_HyperBlaster_Fire(edict_t *ent) { int damage; if (deathmatch->value) damage = 15; else damage = 20; }',
        'void Machinegun_Fire(edict_t *ent) { int damage = 8; int kick = 2; }',
        'void Chaingun_Fire(edict_t *ent) { int damage; if (deathmatch->value) damage = 6; else damage = 8; }',
        'void weapon_shotgun_fire(edict_t *ent) { int damage = 4; int kick = 8; }',
        'void weapon_supershotgun_fire(edict_t *ent) { int damage = 6; int kick = 12; }',
        'void Weapon_Railgun_Fire(edict_t *ent) { int damage = 100; }',
    ])


class PatcherTests(unittest.TestCase):
    def test_all_caps_and_damage(self):
        for edition in ('classic', 'remaster'):
            with self.subTest(edition=edition):
                original = [fixture_client(edition), fixture_upgrade(edition), fixture_weapon(edition)]
                new_client, new_items, new_weapon = patch_sources(original, edition)
                for ammo, (base, bandolier, pack) in CAPS.items():
                    if edition == 'classic':
                        self.assertIn(f'client->pers.max_{ammo} = {base};', new_client)
                        self.assertIn(f'other->client->pers.max_{ammo} = {pack};', new_items)
                        if bandolier is not None:
                            self.assertIn(f'other->client->pers.max_{ammo} = {bandolier};', new_items)
                    else:
                        self.assertIn(f'client->pers.max_ammo[AMMO_{ammo.upper()}] = {base};', new_client)
                        self.assertIn(f'G_AdjustAmmoCap(other, AMMO_{ammo.upper()}, {pack})', new_items)
                        if bandolier is not None:
                            self.assertIn(f'G_AdjustAmmoCap(other, AMMO_{ammo.upper()}, {bandolier})', new_items)
                self.assertIn('base_count *= 2;' if edition == 'remaster' else
                              '(newinfo->base_count * 2)', new_items)
                self.assertIn('inventory[IT_ARMOR_JACKET] = 5;' if edition == 'remaster' else
                              'inventory[jacket_armor_index] = 5;', new_items)
                self.assertIn('inventory[old_armor_index] += 5;', new_items)
                for source_damage, percent in ((4, 20), (6, 20), (8, 20), (15, 50), (20, 50), (6, 20), (15, 50)):
                    self.assertIn(f'Q2ModScaleDamage({source_damage}, {percent})', new_weapon)
                self.assertIn('void Weapon_Railgun_Fire(edict_t *ent) { int damage = 100; }', new_weapon)
                self.assertEqual(new_weapon.count('static int Q2ModScaleDamage'), 1)
                self.assertNotEqual(original[0], new_client)
                self.assertNotEqual(original[1], new_items)
                self.assertNotEqual(original[2], new_weapon)
                with self.assertRaises(ValueError):
                    patch_sources([new_client, new_items, new_weapon], edition)
                if edition == 'remaster':
                    self.assertIn('client->pers.max_ammo.fill(50)', new_client)
                    self.assertIn('G_AdjustAmmoCap(other, AMMO_MAGSLUG, 75)', new_items)
                    self.assertIn('client->pers.max_ammo[AMMO_FLECHETTES] = 200', new_client)

    def test_cli_dryrun_backups_and_modified_source_failure(self):
        for edition in ('classic', 'remaster'):
            with self.subTest(edition=edition), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                ext = '.c' if edition == 'classic' else '.cpp'
                files = [root / ('p_client' + ext), root / ('g_items' + ext), root / ('p_weapon' + ext)]
                originals = [fixture_client(edition), fixture_upgrade(edition), fixture_weapon(edition)]
                for f, contents in zip(files, originals):
                    f.write_text(contents, encoding='utf8')
                self.assertEqual(main([str(root), '--edition', edition, '--dry-run']), 0)
                self.assertEqual([f.read_text(encoding='utf8') for f in files], originals)
                self.assertEqual(main([str(root), '--edition', edition]), 0)
                for f, orig in zip(files, originals):
                    self.assertEqual(Path(str(f) + '.balance-original.bak').read_text(), orig)
                with self.assertRaises(SystemExit):
                    main([str(root), '--edition', edition])

    def test_percentage_expectations(self):
        # Integer damage exact expected values under stochastic rounding.
        for base, pct in ((4, 20), (6, 20), (8, 20), (15, 50), (10, 50), (20, 50)):
            score = base * (100 + pct)
            quotient, remainder = divmod(score, 100)
            expectation = (quotient * (100 - remainder) + (quotient + 1) * remainder) / 100
            self.assertAlmostEqual(expectation, base * (1 + pct / 100))


if __name__ == '__main__':
    unittest.main()