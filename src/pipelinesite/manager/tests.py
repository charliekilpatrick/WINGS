import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from manager.st123.config import EXAMPLE_TARGET, NGC1494_TARGET, campaign_targets
from manager.st123.gaia import format_wcs_quality, load_gaia_overlay
from manager.st123.host_distance import format_distance, lookup_host_distance
from manager.st123.inventory import (
    catalog_sources,
    discover_display_image,
    discover_mosaic_images,
    discover_reference_image,
    dispatch_availability,
    infer_stages,
    remaining_stages,
    resolve_display_image,
    summarize_catalog,
    _dolphot_run_timing,
    _format_image_size,
    _format_timestamp,
)
from manager.st123.photometry import (
    build_filter_plan,
    flux_snr,
    row_ab_mags,
    three_sigma_limit,
    vega_to_ab_offset,
)
from manager.st123.st123api import display_filter, filter_name
from manager.st123.sky import format_sky, reference_heading, tan_pix_to_world, world_to_pix


def _write_phot(path: Path, rows):
    lines = []
    for x, y, snr, sharp, crowd, obj_type in rows:
        cols = ['0'] * 11
        cols[2] = str(x)
        cols[3] = str(y)
        cols[5] = str(snr)
        cols[6] = str(sharp)
        cols[9] = str(crowd)
        cols[10] = str(obj_type)
        lines.append(' '.join(cols))
    path.write_text('\n'.join(lines) + '\n')


class CatalogCutTests(SimpleTestCase):
    def test_quality_cuts_count_before_and_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            phot = Path(tmp) / 'hst_0_0.phot'
            _write_phot(
                phot,
                [
                    (10, 10, 20, 0.01, 0.1, 1),
                    (11, 11, 20, 0.8, 0.1, 1),
                    (12, 12, 20, 0.01, 2.0, 1),
                    (13, 13, 20, 0.01, 0.1, 2),
                ],
            )
            summary = summarize_catalog(
                phot,
                cuts={'types': (1,), 'sharp_max': 0.3, 'crowd_max': 0.5, 'snr_min': None},
            )
            self.assertEqual(summary['n_before'], 4)
            self.assertEqual(summary['n_after'], 1)
            self.assertEqual(summary['rejected']['sharp'], 1)
            self.assertEqual(summary['rejected']['crowd'], 1)
            self.assertEqual(summary['rejected']['type'], 1)


class StageInferenceTests(SimpleTestCase):
    def test_remaining_includes_missing_hdf5(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            download = root / 'download' / 'HST' / 'WFC3' / 'F625W' / '1'
            download.mkdir(parents=True)
            (download / 'frame_flc.fits').write_bytes(b'simple')
            rows = infer_stages(root)
            by_key = {row['key']: row for row in rows}
            self.assertEqual(by_key['download']['state'], 'completed')
            self.assertEqual(by_key['combine_catalogs']['state'], 'pending')
            self.assertIn('combine_catalogs', remaining_stages(rows))


class DolphotRuntimeTests(SimpleTestCase):
    def test_elapsed_from_dolphot_err(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / 'dolphot' / 'hst_0_0'
            run.mkdir(parents=True)
            (run / 'dolphot.param').write_text('img0_file = ref\n')
            (run / 'dolphot.err').write_text('ELAPSED_SEC=693.21\n')
            (run / 'hst_0_0.phot').write_text('0 0 1 1 1 20 0.01 0 0 0.1 1\n')
            _start, _end, seconds = _dolphot_run_timing(root)
            self.assertAlmostEqual(seconds, 693.21)
            rows = infer_stages(root)
            by_key = {row['key']: row for row in rows}
            self.assertEqual(by_key['run_dolphot']['state'], 'completed')
            self.assertEqual(by_key['run_dolphot']['duration'], '11m 33s')


class HostDistanceTests(SimpleTestCase):
    def test_format_and_cache_roundtrip(self):
        self.assertEqual(
            format_distance({
                'distance_mpc': 14.824,
                'distance_err_mpc': 1.553,
                'catalog': 'GLADE+',
            }),
            '14.8 ± 1.6 Mpc (GLADE+)',
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / '.pipelinesite' / 'host_distance.json'
            cache.parent.mkdir(parents=True)
            cache.write_text(
                '{'
                '"key": {"host": "NGC 3913", "ra": 177.65595, "dec": 55.35359},'
                '"distance_mpc": 14.8, "distance_err_mpc": 1.6, "catalog": "GLADE+"'
                '}'
            )
            record = lookup_host_distance(
                host='NGC 3913',
                ra=177.65595,
                dec=55.35359,
                base_dir=root,
            )
            self.assertEqual(record['catalog'], 'GLADE+')
            self.assertEqual(record['distance_mpc'], 14.8)


@override_settings(
    ST123_BASE_DIR='/data/ckilpatrick/HST/2026dix',
    ST123_TARGET_NAME='2026dix',
    ST123_CAMPAIGN_REGISTRY='/tmp/pipelinesite-missing-campaign-targets.json',
)
class CampaignPageTests(TestCase):
    def test_home_and_target_pages_render(self):
        home = self.client.get('/')
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, 'SN 2026dix')
        self.assertContains(home, '18338')
        self.assertContains(home, 'stsci.edu/hst-program-info/program/?program=18338')
        self.assertNotContains(home, 'HST example field')
        self.assertContains(home, 'NGC 3913')
        self.assertNotContains(home, 'IIb')
        self.assertContains(home, 'GLADE+')
        self.assertNotContains(home, 'Dispatch')
        self.assertNotContains(home, '>Target</a>')
        self.assertContains(home, 'Search targets')
        self.assertContains(home, 'NGC 1494')
        self.assertContains(home, 'NGC 784')
        self.assertContains(home, 'Jobs')
        self.assertContains(home, '/ 1 running')
        target = self.client.get('/manager/targets/2026dix')
        self.assertEqual(target.status_code, 200)
        self.assertContains(target, 'Images')
        self.assertContains(target, 'Catalogs')
        self.assertContains(target, 'Host')
        self.assertContains(target, 'NGC 3913')
        self.assertNotContains(target, 'IIb')
        self.assertContains(target, 'Reference image')
        self.assertContains(target, 'WFC3')
        self.assertContains(target, 'F625W')
        self.assertContains(target, 'Download HDF5')
        self.assertContains(target, 'Download mosaic')
        self.assertContains(target, 'data-reference-select')
        self.assertContains(target, 'WFC3 F625W (DOLPHOT reference)')
        self.assertContains(target, 'Quality DOLPHOT sources')
        self.assertContains(target, 'Quality-cut DOLPHOT sources')
        self.assertContains(target, 'Gaia alignment sources')
        self.assertContains(target, 'Gaia stars used for absolute WCS')
        self.assertNotContains(target, 'Science frames under')
        self.assertNotContains(target, 'Reference image + sources')
        self.assertNotContains(target, 'Scroll to zoom')
        self.assertNotContains(target, 'HST example field')
        self.assertContains(target, '11m')
        self.assertNotContains(target, '>Target</a>')
        self.assertNotContains(target, '+00:00')
        self.assertContains(target, '2 × 4096 × 2051')
        self.assertContains(target, '4 × 800 × 800')

    def test_target_search_redirects(self):
        resp = self.client.get('/manager/search', {'q': '2026dix'})
        self.assertEqual(resp.status_code, 302)
        home = self.client.get('/', {'q': '2026dix'})
        self.assertEqual(home.status_code, 302)
        self.assertIn('/manager/targets/2026dix', home['Location'])
        ngc = self.client.get('/', {'q': 'NGC 1494'})
        self.assertEqual(ngc.status_code, 302)
        self.assertIn('/manager/targets/ngc1494', ngc['Location'])
        ngc784 = self.client.get('/', {'q': 'NGC 784'})
        self.assertEqual(ngc784.status_code, 302)
        self.assertIn('/manager/targets/ngc784', ngc784['Location'])

    def test_ngc1494_target_page_renders(self):
        page = self.client.get('/manager/targets/ngc1494')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'NGC 1494')
        self.assertContains(page, '/data/ckilpatrick/HST/ngc1494')
        self.assertContains(page, 'data-dispatch-message')
        self.assertContains(page, 'data-dispatch-allowed')

    def test_ngc784_target_page_renders(self):
        page = self.client.get('/manager/targets/ngc784')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'NGC 784')
        self.assertContains(page, '/data/ckilpatrick/HST/ngc784')
        self.assertContains(page, 'data-dispatch-allowed')
        self.assertContains(page, 'data-reference-select')
        self.assertContains(page, 'ACS F814W (DOLPHOT reference)')
        self.assertContains(page, 'ACS F606W')
        self.assertContains(page, 'WFPC2 F606W')
        self.assertContains(page, 'WFPC2 F814W')
        self.assertNotContains(page, 'align prelim')
        self.assertContains(page, 'Download mosaic')
        self.assertContains(page, 'Download HDF5')


class DispatchGateTests(SimpleTestCase):
    def test_blocks_same_target_and_capacity(self):
        live = [{
            'name': 'ngc1494',
            'display_name': 'NGC 1494',
            'pid': 1,
            'message': 'Running Align',
            'started_at': '2026-09-13T17:23:33',
        }]
        same = dispatch_availability(NGC1494_TARGET, jobs=live, max_jobs=2)
        self.assertFalse(same['allowed'])
        self.assertEqual(same['reason'], 'target_running')
        self.assertIn('already running for NGC 1494', same['message'])
        other = dispatch_availability(EXAMPLE_TARGET, jobs=live, max_jobs=1)
        self.assertFalse(other['allowed'])
        self.assertEqual(other['reason'], 'capacity')
        self.assertIn('already running for NGC 1494', other['message'])
        idle = dispatch_availability(NGC1494_TARGET, jobs=[], max_jobs=1)
        self.assertTrue(idle['allowed'])
        self.assertEqual(idle['reason'], 'ok')

    @override_settings(ST123_DISPATCH_LOCK='/tmp/pipelinesite-test-dispatch.lock')
    @patch('manager.st123.runner.dispatch_availability')
    @patch('manager.st123.runner.subprocess.Popen')
    def test_spawn_job_does_not_start_when_blocked(self, popen, gate):
        from manager.st123.runner import spawn_job

        gate.return_value = {
            'allowed': False,
            'reason': 'target_running',
            'message': 'A job is already running for NGC 1494. Wait for it to finish.',
            'running': 1,
            'max_jobs': 1,
            'jobs': [],
        }
        with self.assertRaises(RuntimeError) as ctx:
            spawn_job(['download'], target=NGC1494_TARGET)
        self.assertIn('already running', str(ctx.exception))
        popen.assert_not_called()


class DispatchViewTests(TestCase):
    @patch('manager.st123.inventory.dispatch_availability')
    def test_target_page_disables_dispatch_when_blocked(self, gate):
        gate.return_value = {
            'allowed': False,
            'reason': 'target_running',
            'message': 'A job is already running for NGC 1494. Wait for it to finish.',
            'running': 1,
            'max_jobs': 1,
            'jobs': [],
        }
        page = self.client.get('/manager/targets/ngc1494')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'A job is already running for NGC 1494')
        self.assertContains(page, 'disabled')
        self.assertContains(page, 'data-dispatch-allowed="0"')

    @patch('manager.views.campaign.spawn_job')
    def test_ajax_second_click_is_rejected(self, spawn):
        spawn.side_effect = RuntimeError(
            'A job is already running for NGC 1494. Wait for it to finish.'
        )
        resp = self.client.post(
            '/manager/targets/ngc1494/dispatch',
            {'target': 'ngc1494'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 409)
        self.assertFalse(resp.json()['ok'])
        self.assertIn('already running', resp.json()['error'])
        spawn.assert_called_once()


class SkyFormatTests(SimpleTestCase):
    def test_tan_and_heading(self):
        ra, dec = tan_pix_to_world(
            2045.392,
            2202.38625,
            [2045.392, 2202.38625],
            [177.66542876963035, 55.35667598884552],
            [[3.70545535332154e-06, 1.04750365511532e-05],
             [1.04750365511532e-05, -3.7054553533215e-06]],
        )
        self.assertAlmostEqual(ra, 177.66542876963035, places=8)
        self.assertAlmostEqual(dec, 55.35667598884552, places=8)
        back = world_to_pix(
            ra,
            dec,
            {
                'crpix': [2045.392, 2202.38625],
                'crval': [177.66542876963035, 55.35667598884552],
                'cd': [
                    [3.70545535332154e-06, 1.04750365511532e-05],
                    [1.04750365511532e-05, -3.7054553533215e-06],
                ],
            },
        )
        self.assertIsNotNone(back)
        self.assertAlmostEqual(back[0], 2045.392, places=4)
        self.assertAlmostEqual(back[1], 2202.38625, places=4)
        self.assertEqual(
            format_sky(177.65595, 55.353589),
            '11:50:37.428 +55:21:12.92',
        )
        self.assertEqual(
            reference_heading({
                'instrument': 'WFC3',
                'detector': 'UVIS',
                'filter': 'F625W',
                'date_obs': '2024-01-25',
            }),
            'Reference image — WFC3/UVIS F625W · 2024-01-25',
        )


class PhotometryParseTests(SimpleTestCase):
    def test_combined_vega_to_ab(self):
        self.assertAlmostEqual(vega_to_ab_offset('WFPC2', 'F606W'), 0.100)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            columns = root / 'run.phot.columns'
            phot = root / 'run.phot'
            columns.write_text(
                '1. Extension\n'
                '2. Chip\n'
                '3. Object X position\n'
                '4. Object Y position\n'
                '5. Chi for fit\n'
                '6. Signal-to-noise\n'
                '7. Object sharpness\n'
                '8. Object roundness\n'
                '9. Direction of major axis\n'
                '10. Crowding\n'
                '11. Object type\n'
                '12. Pass Detected\n'
                '13. Total counts, WFPC2_F606W\n'
                '17. Instrumental VEGAMAG magnitude, WFPC2_F606W\n'
                '19. Magnitude uncertainty, WFPC2_F606W\n'
            )
            cols = ['0'] * 20
            cols[2] = '10.0'
            cols[3] = '12.0'
            cols[4] = '1.1'
            cols[5] = '30'
            cols[6] = '0.01'
            cols[7] = '0.02'
            cols[9] = '0.1'
            cols[10] = '1'
            cols[16] = '24.234'
            cols[18] = '0.168'
            phot.write_text(' '.join(cols) + '\n')
            plan = build_filter_plan(columns)
            mags = row_ab_mags(cols, plan)
            self.assertEqual(len(mags), 1)
            self.assertEqual(mags[0]['name'], 'WFPC2 F606W')
            self.assertAlmostEqual(mags[0]['mag'], 24.334)
            self.assertAlmostEqual(mags[0]['magerr'], 0.168)
            self.assertFalse(mags[0]['is_limit'])
            sources = catalog_sources(phot)
            self.assertEqual(sources[0]['mags'][0]['system'], 'AB')
            self.assertAlmostEqual(sources[0]['mags'][0]['mag'], 24.334)


class PhotometryLimitTests(SimpleTestCase):
    def test_three_sigma_limit_from_large_error(self):
        self.assertAlmostEqual(flux_snr(1.653), 1.0857362047581294 / 1.653, places=5)
        limit = three_sigma_limit(27.135, 1.653)
        self.assertAlmostEqual(limit, 25.486, places=2)
        row = {
            'mag': 27.135,
            'magerr': 1.653,
            'snr': flux_snr(1.653),
            'is_limit': True,
            'limit_mag': limit,
        }
        self.assertTrue(row['is_limit'])
        self.assertLess(row['limit_mag'], 27.135)


class TimestampFormatTests(SimpleTestCase):
    def test_iso_seconds_only(self):
        from datetime import datetime, timezone

        self.assertEqual(
            _format_timestamp(datetime(2026, 8, 4, 17, 50, 19, 453737, tzinfo=timezone.utc)),
            '2026-08-04T17:50:19',
        )
        self.assertEqual(_format_image_size([(2051, 4096), (2051, 4096)]), '2 × 4096 × 2051')
        self.assertEqual(
            _format_image_size([(800, 800), (800, 800), (800, 800), (800, 800)]),
            '4 × 800 × 800',
        )


class GaiaOverlayTests(SimpleTestCase):
    def test_on_image_and_used_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gaia_dir = root / 'reduction' / 'gaia'
            l3_dir = root / 'reduction' / 'jhat' / 'l3_ref'
            gaia_dir.mkdir(parents=True)
            l3_dir.mkdir(parents=True)
            (gaia_dir / 'gaiadr3_radec.txt').write_text(
                '# ra dec\n'
                '177.66542877 55.35667599\n'
                '180.0 0.0\n'
            )
            (l3_dir / 'coadd.phot.txt').write_text(
                'ra dec mag x y dmag\n'
                '177.66543 55.35668 -3.0 100 100 0.05\n'
            )
            wcs = {
                'crpix': [2045.392, 2202.38625],
                'crval': [177.66542876963035, 55.35667598884552],
                'cd': [
                    [3.70545535332154e-06, 1.04750365511532e-05],
                    [1.04750365511532e-05, -3.7054553533215e-06],
                ],
                'nx': 4091,
                'ny': 4405,
            }
            overlay = load_gaia_overlay(root, wcs)
            self.assertEqual(overlay['n_on_image'], 1)
            self.assertEqual(overlay['n_used'], 1)
            self.assertTrue(overlay['stars'][0]['used'])
            self.assertIsNotNone(overlay['rms_mas'])
            self.assertIn('RMS =', format_wcs_quality(overlay))


class MosaicImageTests(SimpleTestCase):
    def test_ngc784_lists_mosaic_filters_only(self):
        root = Path('/data/ckilpatrick/HST/ngc784')
        mosaics = discover_mosaic_images(root)
        keys = {(row['instrument'], row['filter'], row['stage']) for row in mosaics}
        self.assertIn(('ACS', 'F606W', 'mosaic'), keys)
        self.assertIn(('ACS', 'F814W', 'mosaic'), keys)
        self.assertIn(('WFPC2', 'F606W', 'mosaic'), keys)
        self.assertIn(('WFPC2', 'F814W', 'mosaic'), keys)
        self.assertEqual(len(mosaics), 4)
        self.assertTrue(all(row['stage'] == 'mosaic' for row in mosaics))
        selected = next(row for row in mosaics if row['selected'])
        self.assertEqual(selected['instrument'], 'ACS')
        self.assertEqual(selected['filter'], 'F814W')
        self.assertEqual(selected['option_label'], 'ACS F814W (DOLPHOT reference)')
        switched = resolve_display_image(root, 'mosaic-acs-f606w')
        self.assertIsNotNone(switched)
        self.assertIn('f606w', switched.name.lower())

    def test_2026dix_mosaic_dropdown_includes_wfc3_and_wfpc2(self):
        root = Path('/data/ckilpatrick/HST/2026dix')
        mosaics = discover_mosaic_images(root)
        filters = {(row['instrument'], row['filter']) for row in mosaics if row['stage'] == 'mosaic'}
        self.assertIn(('WFC3', 'F625W'), filters)
        self.assertIn(('WFC3', 'F336W'), filters)
        self.assertIn(('WFPC2', 'F814W'), filters)


class DisplayImageTests(SimpleTestCase):
    def test_ngc1494_uses_full_field_not_stamp(self):
        root = Path('/data/ckilpatrick/HST/ngc1494')
        stamp = discover_reference_image(root)
        display = discover_display_image(root)
        self.assertIsNotNone(stamp)
        self.assertIsNotNone(display)
        self.assertNotEqual(display, stamp)
        self.assertIn('l3_ref', str(display))
        from manager.st123.sky import read_image_header
        stamp_hdr = read_image_header(stamp)
        display_hdr = read_image_header(display)
        self.assertGreater(
            (display_hdr['nx'] or 0) * (display_hdr['ny'] or 0),
            4 * (stamp_hdr['nx'] or 0) * (stamp_hdr['ny'] or 0),
        )

    def test_2026dix_keeps_full_dolphot_reference(self):
        root = Path('/data/ckilpatrick/HST/2026dix')
        stamp = discover_reference_image(root)
        display = discover_display_image(root)
        self.assertEqual(stamp, display)


class St123FilterTests(SimpleTestCase):
    def test_acs_clear_wheel_uses_st123_get_filter(self):
        root = Path('/data/ckilpatrick/HST/ngc784/download')
        frames = sorted(root.rglob('j8yy12ptq_flc.fits')) + sorted(root.rglob('j8yy12pqq_flc.fits'))
        self.assertEqual(len(frames), 2)
        self.assertEqual(display_filter(filter_name(frames[0])), 'F606W')
        self.assertEqual(display_filter(filter_name(frames[1])), 'F814W')


_VISIT_HTML = """
<table id="visits2">
  <tr>
    <td class="center-cell">01</td>
    <td>Archived</td>
    <td>NGC7814<br></td>
    <td>WFC3/UVIS<br></td>
    <td>1</td>
    <td>n/a</td>
  </tr>
  <tr>
    <td class="center-cell">02</td>
    <td>Implementation</td>
    <td>ANY<br>NGC0157<br></td>
    <td>WFC3/UVIS<br>ACS/WFC<br></td>
    <td>2</td>
    <td>Not ready</td>
  </tr>
</table>
"""


class ProgramSyncTests(SimpleTestCase):
    def test_parse_visits_and_ready_only_when_observed_and_in_mast(self):
        from manager.st123.program_sync import (
            parse_visit_table,
            pretty_target_name,
            sync_program_targets,
            visit_is_observed,
        )

        self.assertEqual(pretty_target_name('NGC0157'), 'NGC 157')
        self.assertTrue(visit_is_observed('Archived'))
        self.assertFalse(visit_is_observed('Implementation'))
        visits = parse_visit_table(_VISIT_HTML)
        self.assertEqual(len(visits), 2)
        self.assertEqual(visits[0]['targets'], ['NGC 7814'])
        self.assertTrue(visits[0]['observed'])
        self.assertEqual(visits[1]['targets'], ['NGC 157'])
        self.assertFalse(visits[1]['observed'])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / 'campaign_targets.json'
            mast = [
                {
                    'target_name': 'NGC7814',
                    'key': 'NGC7814',
                    'ra': 10.0,
                    'dec': 16.0,
                    'instruments': ('WFC3',),
                    'obs_id': 'iexx01',
                    'public': True,
                },
                {
                    'target_name': 'NGC0157',
                    'key': 'NGC157',
                    'ra': 8.0,
                    'dec': -8.0,
                    'instruments': ('ACS',),
                    'obs_id': 'iexx02',
                    'public': True,
                },
            ]
            result = sync_program_targets(
                program='18338',
                registry_path=registry,
                root=root,
                visit_html=_VISIT_HTML,
                mast_rows=mast,
            )
            self.assertEqual(result['n_ready'], 1)
            self.assertEqual(result['added'], ['ngc7814'])
            ready = [row for row in result['targets'] if row['ready']]
            self.assertEqual(ready[0]['display_name'], 'NGC 7814')
            self.assertTrue((root / 'ngc7814').is_dir())
            with override_settings(ST123_CAMPAIGN_REGISTRY=str(registry)):
                names = [spec.name for spec in campaign_targets()]
            self.assertIn('ngc7814', names)
            self.assertNotIn('ngc157', names)
