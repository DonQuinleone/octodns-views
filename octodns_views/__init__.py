'''Split-horizon views for octoDNS.

A record lists per-view overrides under ``octodns.views``, and the ``Views``
processor maps each view to the targets that should serve it::

    processors:
      views:
        class: octodns_views.Views
        views:
          inside: [internal-dns]

When octoDNS plans a target in a view, each record that carries an override for
that view is replaced by the override, which may change the record's type.
Targets outside every view get the records unchanged.
'''

from logging import getLogger

from octodns.context import ContextDict
from octodns.processor.base import BaseProcessor, ProcessorException
from octodns.record import Record
from octodns.record import ValidationError as RecordValidationError
from octodns.zone.base import DuplicateRecordException, SubzoneRecordException
from octodns.zone.exception import ValidationError as ZoneValidationError

__version__ = '0.1.0'

VIEWS_KEY = 'views'


class Views(BaseProcessor):
    '''Replace records with their per-view override for targets in a view.

    ``views`` maps a view name to the list of target ids that serve it. A target
    may appear in at most one view. When the source zone is processed, every
    view is applied to a copy of the zone and the result validated, so an
    unknown view, an invalid override or an override that leaves the zone
    invalid fails the plan before any target is touched. For each target the
    ``views`` data is removed from every record, and for a target in a view the
    target's own support checks run again over the overrides.
    '''

    def __init__(self, name, views, **kwargs):
        super().__init__(name, **kwargs)
        self.log = getLogger(f'Views[{name}]')
        self.view_by_target = self._targets_by_view(views)
        self.view_names = frozenset(views)

    @staticmethod
    def _targets_by_view(views):
        if not isinstance(views, dict):
            raise ProcessorException('views must map view names to targets')
        view_by_target = {}
        for view, targets in views.items():
            if (
                not isinstance(targets, list)
                or not targets
                or not all(isinstance(t, str) for t in targets)
            ):
                raise ProcessorException(
                    f'view {view} must list one or more target ids'
                )
            for target in targets:
                if target in view_by_target:
                    raise ProcessorException(
                        f'target {target} is in views {view_by_target[target]} '
                        f'and {view}; a target can serve only one view'
                    )
                view_by_target[target] = view
        return view_by_target

    def _overrides(self, record):
        overrides = record.octodns.get(VIEWS_KEY, {})
        if not isinstance(overrides, dict):
            raise ProcessorException(
                f'{record.fqdn}: octodns.views must map view names to overrides'
            )
        return overrides

    @staticmethod
    def _settings_without_views(record):
        return {k: v for k, v in record.octodns.items() if k != VIEWS_KEY}

    def _override(self, record, override, zone, lenient):
        if not isinstance(override, dict):
            raise ProcessorException(
                f'{record.fqdn}: a view override must be a record mapping'
            )
        if 'octodns' in override:
            raise ProcessorException(
                f'{record.fqdn}: a view override cannot set octodns; it '
                'takes the octodns settings of the record it overrides'
            )
        data = {'type': record._type, 'ttl': record.ttl, **override}
        settings = self._settings_without_views(record)
        if settings:
            data['octodns'] = settings
        try:
            return Record.new(
                zone,
                record.name,
                ContextDict(data, context=record.context),
                source=record.source,
                lenient=lenient,
            )
        except RecordValidationError as e:
            raise ProcessorException(
                f'{record.fqdn}: invalid view override: {e}'
            ) from e

    def _without_views(self, record):
        copy = record.copy()
        copy.octodns = self._settings_without_views(record)
        return copy

    def _apply_view(self, zone, view, lenient):
        '''Swap every record carrying views data for its replacement in
        ``zone``: the override for ``view`` where there is one, otherwise the
        record without its views data. All removals happen before any
        addition, so overrides that swap types at one name work in any order.
        '''
        swaps = []
        for record in zone.records:
            if VIEWS_KEY not in record.octodns:
                continue
            override = self._overrides(record).get(view)
            if override is None:
                swaps.append((record, self._without_views(record)))
            else:
                swaps.append(
                    (record, self._override(record, override, zone, lenient))
                )
        for record, _ in swaps:
            zone.remove_record(record)
        for record, replacement in swaps:
            try:
                zone.add_record(replacement, lenient=lenient)
            except (DuplicateRecordException, SubzoneRecordException) as e:
                raise ProcessorException(
                    f'{record.fqdn}: view {view}: {e}'
                ) from e

    def process_source_zone(self, desired, sources, lenient=False):
        lenient = self.lenient or lenient
        for record in desired.records:
            for view in self._overrides(record):
                if view not in self.view_names:
                    raise ProcessorException(
                        f'{record.fqdn}: override for unknown view {view}'
                    )
        for view in sorted(self.view_names):
            simulated = desired.copy()
            self._apply_view(simulated, view, lenient)
            try:
                simulated.validate(lenient=lenient)
            except ZoneValidationError as e:
                raise ProcessorException(
                    f'view {view} leaves the zone invalid: {e}'
                ) from e
        return desired

    def process_source_and_target_zones(
        self, desired, existing, target, lenient=False
    ):
        lenient = self.lenient or lenient
        view = self.view_by_target.get(target.id)
        self._apply_view(desired, view, lenient)
        if view is not None:
            # The target's support checks ran before processors, so run them
            # again over the overrides.
            desired = target._process_desired_zone(desired)
        return desired, existing
