from django.conf import settings

from manager.st123.config import target_config


def campaign(request):
    target = target_config()
    return {
        'example_target_name': target.name,
        'example_target_display': target.display_name,
        'program_name': getattr(settings, 'PROGRAM_NAME', 'Nearby Galaxies Program'),
        'program_short': getattr(settings, 'PROGRAM_SHORT', 'NGP'),
        'hst_program_id': getattr(settings, 'HST_PROGRAM_ID', '18338'),
        'hst_program_url': getattr(
            settings,
            'HST_PROGRAM_URL',
            'https://www.stsci.edu/hst-program-info/program/?program=18338',
        ),
        'hst_program_title': getattr(settings, 'HST_PROGRAM_TITLE', ''),
    }
