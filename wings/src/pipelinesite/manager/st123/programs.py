"""HST programs tracked by the site. Campaigns are one program each."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProgramSpec:
    program_id: str
    title: str
    short_name: str
    url: str
    pi: str = ''
    institution: str = ''
    cycle: str = ''
    orbits: str = ''
    status: str = ''
    include_example: bool = False
    include_fixed: bool = False
    include_planned: bool = False
    registry_filename: str = 'campaign_targets.json'
    output_name: str = ''


def _stsci_url(program_id: str) -> str:
    return f'https://www.stsci.edu/hst-program-info/program/?program={program_id}'


PROGRAMS: tuple[ProgramSpec, ...] = (
    ProgramSpec(
        program_id='18338',
        short_name='GO 18338',
        title='Completing a Legacy Dataset with Deep HST Imaging of 121 Nearby Star-Forming Galaxies',
        url=_stsci_url('18338'),
        pi='Charles Kilpatrick',
        institution='Northwestern University',
        cycle='34',
        orbits='193',
        status='Implementation',
        include_example=False,
        include_fixed=False,
        registry_filename='campaign_targets.json',
        output_name='go18338',
    ),
    ProgramSpec(
        program_id='18440',
        short_name='GO 18440',
        title='Catch Them While They\'re Hot (And Then Not): An HST Search for Hot Failed Supernovae',
        url=_stsci_url('18440'),
        pi='Maria Drout',
        institution='University of Toronto',
        cycle='34',
        orbits='40',
        status='Implementation',
        include_example=False,
        include_fixed=False,
        include_planned=True,
        registry_filename='campaign_targets.json',
        output_name='go18440',
    ),
)


def _norm(value: str | None) -> str:
    return ''.join(ch for ch in str(value or '').lower() if ch.isalnum())


def list_program_specs() -> tuple[ProgramSpec, ...]:
    return PROGRAMS


def find_program(program_id: str | None) -> ProgramSpec | None:
    want = _norm(program_id)
    if not want:
        return None
    if want.startswith('go') and want[2:].isdigit():
        want = want[2:]
    for spec in PROGRAMS:
        if want in {_norm(spec.program_id), _norm(spec.short_name)}:
            return spec
    return None


def default_program() -> ProgramSpec:
    return PROGRAMS[0]
