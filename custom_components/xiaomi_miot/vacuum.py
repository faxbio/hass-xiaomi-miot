"""Support for Xiaomi vacuums."""
import logging
from datetime import timedelta

from homeassistant.const import *
from homeassistant.components.vacuum import (  # noqa: F401
    DOMAIN as ENTITY_DOMAIN,
    StateVacuumEntity,
    SUPPORT_TURN_ON,
    SUPPORT_TURN_OFF,
    SUPPORT_PAUSE,
    SUPPORT_STOP,
    SUPPORT_RETURN_HOME,
    SUPPORT_FAN_SPEED,
    SUPPORT_BATTERY,
    SUPPORT_STATUS,
    SUPPORT_SEND_COMMAND,
    SUPPORT_LOCATE,
    SUPPORT_CLEAN_SPOT,
    SUPPORT_MAP,
    SUPPORT_STATE,
    SUPPORT_START,
    STATE_CLEANING,
    STATE_DOCKED,
    STATE_RETURNING,
    STATE_ERROR,
)

from . import (
    DOMAIN,
    CONF_MODEL,
    XIAOMI_CONFIG_SCHEMA as PLATFORM_SCHEMA,  # noqa: F401
    MiotDevice,
    MiotEntity,
    bind_services_to_entries,
)
from .core.miot_spec import (
    MiotSpec,
    MiotService,
)

_LOGGER = logging.getLogger(__name__)
DATA_KEY = f'{ENTITY_DOMAIN}.{DOMAIN}'
SCAN_INTERVAL = timedelta(seconds=60)

SERVICE_TO_METHOD = {}


async def async_setup_entry(hass, config_entry, async_add_entities):
    config = hass.data[DOMAIN]['configs'].get(config_entry.entry_id, dict(config_entry.data))
    await async_setup_platform(hass, config, async_add_entities)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    hass.data.setdefault(DATA_KEY, {})
    config.setdefault('add_entities', {})
    config['add_entities'][ENTITY_DOMAIN] = async_add_entities
    model = str(config.get(CONF_MODEL) or '')
    entities = []
    miot = config.get('miot_type')
    if miot:
        spec = await MiotSpec.async_from_type(hass, miot)
        for srv in spec.get_services(ENTITY_DOMAIN):
            if not srv.get_property('status'):
                continue
            cfg = {
                **config,
                'name': f"{config.get('name')} {srv.description}"
            }
            entities.append(MiotVacuumEntity(cfg, srv))
    for entity in entities:
        hass.data[DOMAIN]['entities'][entity.unique_id] = entity
    async_add_entities(entities, update_before_add=True)
    bind_services_to_entries(hass, SERVICE_TO_METHOD)


class MiotVacuumEntity(MiotEntity, StateVacuumEntity):
    def __init__(self, config: dict, miot_service: MiotService):
        name = config[CONF_NAME]
        host = config[CONF_HOST]
        token = config[CONF_TOKEN]
        _LOGGER.info('Initializing %s with host %s (token %s...)', name, host, token[:5])

        mapping = miot_service.spec.services_mapping(
            ENTITY_DOMAIN, 'battery', 'identify', 'map', 'order', 'point_zone',
            'roborock_vacuum', 'viomi_vacuum', 'vacuum_extend', 'clean_logs',
        ) or {}
        mapping.update(miot_service.mapping())
        self._device = MiotDevice(mapping, host, token)
        super().__init__(name, self._device, miot_service, config=config)
        self._add_entities = config.get('add_entities') or {}

        self._prop_power = miot_service.get_property('on', 'power')
        self._prop_status = miot_service.get_property('status')
        self._prop_mode = miot_service.get_property('fan_level', 'mode')
        self._act_start = miot_service.get_action('start_sweep')
        self._act_pause = miot_service.get_action('pause_sweeping')
        self._act_stop = miot_service.get_action('stop_sweeping')
        self._act_locate = miot_service.get_action('position')
        self._prop_battery = miot_service.get_property('battery_level')
        self._srv_battery = miot_service.spec.get_service('battery')
        if self._srv_battery:
            self._prop_battery = self._srv_battery.get_property('battery_level')
        self._srv_audio = miot_service.spec.get_service('audio', 'voice')
        if self._srv_audio and not self._act_locate:
            self._act_locate = self._srv_battery.get_property('position', 'find_device')

        if self._prop_power:
            self._supported_features |= SUPPORT_TURN_ON
            self._supported_features |= SUPPORT_TURN_OFF
        if self._act_start:
            self._supported_features |= SUPPORT_START
        if self._act_pause:
            self._supported_features |= SUPPORT_PAUSE
        if self._act_stop:
            self._supported_features |= SUPPORT_STOP
            self._supported_features |= SUPPORT_RETURN_HOME
        if self._prop_mode:
            self._supported_features |= SUPPORT_FAN_SPEED
        if self._prop_battery:
            self._supported_features |= SUPPORT_BATTERY
        if self._prop_status:
            self._supported_features |= SUPPORT_STATUS
            self._supported_features |= SUPPORT_STATE
        if self._act_locate:
            self._supported_features |= SUPPORT_LOCATE

        self._state_attrs.update({'entity_class': self.__class__.__name__})

    @property
    def status(self):
        if self._prop_status:
            val = self._prop_status.from_dict(self._state_attrs)
            if val is not None:
                return self._prop_status.list_description(val)
        return None

    @property
    def state(self):
        if self._prop_status:
            val = self._prop_status.from_dict(self._state_attrs)
            if val is not None:
                pass
            elif val in self._prop_status.list_search(
                'Cleaning', 'Sweeping', 'Mopping', 'Sweeping and Mopping',
                'Part Sweeping', 'Zone Sweeping', 'Select Sweeping',
                'Working', 'Busy',
            ):
                return STATE_CLEANING
            elif val in self._prop_status.list_search('Idle', 'Sleep', 'Charging'):
                return STATE_DOCKED
            elif val in self._prop_status.list_search('Go Charging'):
                return STATE_RETURNING
            elif val in self._prop_status.list_search('Error'):
                return STATE_ERROR
        return None

    @property
    def battery_level(self):
        if self._prop_battery:
            return self._prop_battery.from_dict(self._state_attrs)
        return None

    def turn_on(self, **kwargs):
        if self._prop_power:
            self.set_property(self._prop_power.full_name, True)
        return self.start()

    def turn_off(self, **kwargs):
        return self.stop()

    def start(self):
        if self._act_start:
            return self.miot_action(self._miot_service.iid, self._act_start.iid)
        return False

    def stop(self, **kwargs):
        if self._act_stop:
            return self.miot_action(self._miot_service.iid, self._act_stop.iid)
        return False

    def pause(self):
        if self._act_pause:
            return self.miot_action(self._miot_service.iid, self._act_pause.iid)
        return self.stop()

    def start_pause(self, **kwargs):
        sta = self.state
        if sta == STATE_CLEANING:
            return self.pause()
        return self.start()

    def return_to_base(self, **kwargs):
        if self._srv_battery:
            act = self._srv_battery.get_action('start_charge')
            if act:
                return self.miot_action(self._srv_battery.iid, act.iid)
        return self.stop()

    def locate(self, **kwargs):
        if self._act_locate:
            return self.miot_action(self._act_locate.service.iid, self._act_locate.iid)
        return False

    def clean_spot(self, **kwargs):
        raise NotImplementedError()

    @property
    def fan_speed(self):
        if self._prop_mode:
            val = self._prop_mode.from_dict(self._state_attrs)
            if val is not None:
                return self._prop_mode.list_description(val)
        return None

    @property
    def fan_speed_list(self):
        if self._prop_mode:
            return self._prop_mode.list_description(None) or []
        return None

    def set_fan_speed(self, fan_speed, **kwargs):
        if self._prop_mode:
            val = self._prop_mode.list_value(fan_speed)
            return self.set_property(self._prop_mode.full_name, val)
        return False
