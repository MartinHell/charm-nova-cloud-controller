
from charmhelpers.core.hookenv import config, relation_ids, relation_set
from charmhelpers.core.host import apt_install, filter_installed_packages
from charmhelpers.contrib.openstack import context, neutron, utils

from charmhelpers.contrib.hahelpers.cluster import (
    determine_api_port, determine_haproxy_port)


class ApacheSSLContext(context.ApacheSSLContext):

    interfaces = ['https']
    external_ports = []
    service_namespace = 'nova'

    def __call__(self):
        # late import to work around circular dependency
        from nova_cc_utils import determine_ports
        self.external_ports = determine_ports()
        return super(ApacheSSLContext, self).__call__()


class VolumeServiceContext(context.OSContextGenerator):
    interfaces = []

    def __call__(self):
        ctxt = {}

        os_vers = utils.get_os_codename_package('nova-common')

        if (relation_ids('nova-volume-service') and
           os_vers in ['essex', 'folsom']):
            # legacy nova-volume support, only supported in E and F
            ctxt['volume_service_config'] = 'nova.volume.api.API'
            install_pkg = filter_installed_packages(['nova-api-os-volume'])
            if install_pkg:
                apt_install(install_pkg)
        elif relation_ids('cinder-volume-service'):
            ctxt['volume_service_config'] = 'nova.volume.cinder.API'
            # kick all compute nodes to know they should use cinder now.
            [relation_set(volume_service='cinder', rid=rid)
             for rid in relation_ids('cloud-compute')]
        return ctxt


class HAProxyContext(context.HAProxyContext):
    interfaces = ['ceph']

    def __call__(self):
        '''
        Extends the main charmhelpers HAProxyContext with a port mapping
        specific to this charm.
        Also used to extend nova.conf context with correct api_listening_ports
        '''
        from nova_cc_utils import api_port
        ctxt = super(HAProxyContext, self).__call__()
        if not ctxt:
            # we do not have any other peers, do not load balance yet.
            return {}

        ctxt = {
            'osapi_compute_listen_port': api_port('nova-api-os-compute'),
            'ec2_listen_port': api_port('nova-api-ec2'),
            's3_listen_port': api_port('nova-objectstore'),
        }
        port_mapping = {
            'nova-api-os-compute': [
                determine_haproxy_port(api_port('nova-api-os-compute')),
                determine_api_port(api_port('nova-api-os-compute'))
            ],
            'nova-api-ec2': [
                determine_haproxy_port(api_port('nova-api-ec2')),
                determine_api_port(api_port('nova-api-ec2'))
            ],
            'nova-objectstore': [
                determine_haproxy_port(api_port('nova-objectstore')),
                determine_api_port(api_port('nova-objectstore'))
            ],
        }

        if relation_ids('nova-volume-service'):
            port_mapping.update({
                'nova-api-ec2': [
                    determine_haproxy_port(api_port('nova-api-ec2')),
                    determine_api_port(api_port('nova-api-ec2'))]
            })
            ctxt['osapi_volume_listen_port'] = api_port('nova-api-os-volume')

        if neutron.network_manager() in ['neutron', 'quantum']:
            port_mapping.update({
                'neutron-server': [
                    determine_haproxy_port(api_port('neutron-server')),
                    determine_api_port(api_port('neutron-server'))]
            })
            ctxt['bind_port'] = api_port('neutron-server')
        ctxt['service_ports'] = port_mapping


class NeutronCCContext(context.NeutronContext):
    interfaces = []

    @property
    def plugin(self):
        return neutron.neutron_plugin()

    @property
    def network_manager(self):
        return neutron.network_manager()

    @property
    def neutron_security_groups(self):
        sec_groups = (config('neutron-security-groups') or
                      config('quantum-security-groups'))
        return sec_groups.lower() == 'yes'
