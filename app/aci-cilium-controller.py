#!/usr/local/bin/python3
import os
import logging
import asyncio
import random
from kubernetes_asyncio import client, config, watch
from pyaci import Node, options, filters
from pprint import pformat
from datetime import datetime
#If you need to look at the API calls this is what you do

#logging.getLogger('pyaci').setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
formatter = logging.Formatter(
        '%(asctime)s %(name)-1s %(levelname)-1s [%(threadName)s] %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

class ACCEnvVariables(object):
    '''Parse the environment variables'''
    def __init__(self, dict_env:dict = None):
        """Constructor with real environment variables"""
        super().__init__()
        self.dict_env = dict_env
        self.mode = self.enviro().get("MODE")
        if self.mode is None:
            self.mode = "None"
        self.apic_ip = self.enviro().get("APIC_IPS")
        if self.apic_ip is not None:
            self.apic_ip = self.apic_ip.split(',')
        else:
            self.apic_ip = []
        if self.mode ==  "LOCAL":
            self.aciMetaFilePath = self.enviro().get("ACI_META_FILE", "/tmp/aci-meta-vkaci.json")
        else:
            self.aciMetaFilePath = self.enviro().get("ACI_META_FILE", "/app/aci-meta/aci-meta.json")

        self.tenant = self.enviro().get("TENANT")
        self.app = self.enviro().get("APP")
        self.vrf_tenant = self.enviro().get("VRF_TENANT")
        self.vrf = self.enviro().get("VRF")
        self.l3out_name = self.enviro().get("L3OUT_NAME")
        self.kube_config = self.enviro().get("KUBE_CONFIG")
        self.cert_user= self.enviro().get("CERT_USER")
        self.cert_name= self.enviro().get("CERT_NAME")
        self.key_path= self.enviro().get("KEY_PATH")
        self.contract_master = self.enviro().get("CONTRACT_MASTER")
        logger.info("Parsed Environment Variables %s", pformat(vars(self)))

    def enviro(self):
        '''Return the Dictionary with all the Environment Variables'''
        if self.dict_env is None:
            return os.environ
        else:
            return self.dict_env
        
class ACController(object):
    '''Main Controller Class'''
    def __init__(self, env:ACCEnvVariables):
        """Constructor with real environment variables"""
        super().__init__()
        self.env = env
        self.esg_enabled_ns = []
        self.extEPG_svc = []
        self.apics = []
        self.booting = True

        # Check APIC Ips
        if self.env.apic_ip is None or len(self.env.apic_ip) == 0:
            logger.error("Invalid APIC IP addresses.")
            exit()

        #Create list of APICs and set the useX509CertAuth parameters
        for i in self.env.apic_ip:
            self.apics.append(Node('https://' + i, aciMetaFilePath=self.env.aciMetaFilePath))
        logger.info("APICs To Probe %s", self.env.apic_ip)
        for apic in self.apics:
            if self.is_local_mode():
                logger.info("Running in Local Mode")
                #logger.debug("using %s as user name, %s as certificate name and %s as key path", self.env.cert_user, self.env.cert_name, self.env.key_path)
                apic.useX509CertAuth(self.env.cert_user, self.env.cert_name, self.env.key_path)
            elif self.is_cluster_mode():
                logger.info("Running in Cluster Mode") 
                #logger.debug("using %s as user name, %s as certificate name and key is loaded as a K8s Secret ", self.env.cert_user, self.env.cert_name)
                apic.useX509CertAuth(self.env.cert_user, self.env.cert_name, '/usr/local/etc/aci-cert/user.key')
            else:
                logger.error("MODE can only be LOCAL or CLUSTER but %s was given", self.env.mode)
                return
        
        # Get the Uni MIT and Push the AppProfile.
        uni = apic.mit.polUni()
        uni.fvTenant(self.env.tenant).fvAp(self.env.app).POST()
    
    def is_local_mode(self):
        '''Check if we are running in local mode: Not in a K8s cluster'''
        return self.env.mode.casefold() == "LOCAL".casefold()

    def is_cluster_mode(self):
        '''Check if we are running in cluster mode: in a K8s cluster'''
        return self.env.mode.casefold() == "CLUSTER".casefold()
    
    def randApic(self):
        return random.choice(self.apics)

    def get_fvip(self, apic: Node, ip: str):
        '''Return the Mac addresses on the IP in the VRF '''
        vrfDn = self.aci_vrf = 'uni/tn-' + self.env.vrf_tenant + '/ctx-' + self.env.vrf
        return self.randApic().methods.ResolveClass('fvIp').GET(**options.filter(\
                filters.Eq('fvIp.vrfDn', vrfDn) &\
                filters.Eq('fvIp.addr', ip) &\
                filters.Eq('fvIp.baseEpgDn', '')
                ))
    def get_epiptagDn(self, pod):
        epiptagDn = 'uni/tn-' + self.env.tenant + '/eptags/epiptag-[' + pod.status.pod_ip + ']-' + self.env.vrf
        logger.debug("Calculated epiptagDn %s", epiptagDn)
        return random.choice(self.apics).mit.FromDn(epiptagDn)
    
    def set_tag_pod(self, pod,tag_id):
        epiptag = self.get_epiptagDn(pod)
        logger.info("Adding Policy TAG tag namespace:%s from Pod %s with IP %s", tag_id, pod.metadata.name,pod.status.pod_ip)
        epiptag.POST()
        epiptag.tagTag(key='namespace',value=tag_id).POST()

    def clear_tag_pod(self, pod, tag_id):
        epiptag = self.get_epiptagDn(pod)
        logger.info("Removing Policy TAG tag namespace:%s from Pod %s with IP %s", tag_id, pod.metadata.name,pod.status.pod_ip)
        epiptag.tagTag(key='namespace',value=tag_id).DELETE()
    
    def create_extEPG(self, svc):
        uni = self.randApic().mit.polUni()
        # Up() makes the post happening at the parent of the l3extSubnet object since the l3extInstP is non existent.
        uni.fvTenant(self.env.tenant).\
            l3extOut(self.env.l3out_name).\
                l3extInstP(svc.metadata.namespace + '-' + svc.metadata.name ).\
                    l3extSubnet(ip=svc.status.load_balancer.ingress[0].ip + '/32').Up().POST() 

    def delete_extEPG(self, svc):
        uni = self.randApic().mit.polUni()
        l3extOut = uni.fvTenant(self.env.tenant).l3extOut(self.env.l3out_name)
        l3extOut.l3extInstP(svc.metadata.namespace + '-' + svc.metadata.name ).DELETE()

    async def watch_namespaces(self):
        while self.booting:
            logger.info("Waiting for POD to be loaded before watching Namespaces so we don't TAG twice")
            await asyncio.sleep(5)
        async with client.ApiClient() as api:
            v1 = client.CoreV1Api(api)
            async with watch.Watch().stream(v1.list_namespace) as stream:
                async for event in stream:
                    etype, obj = event["type"], event["object"]
                    # If a  NS becomes ESG Enabled, create the ESG in ACI and then add the tag to all the existing PODs
                    if obj.metadata.labels.get("esg-enabled") == "true" and obj.metadata.name not in self.esg_enabled_ns:
                        self.esg_enabled_ns.append(obj.metadata.name)
                        logger.info("New Namespace: %s is ESG Enabled", obj.metadata.name)
                        uni  = self.randApic().mit.polUni()
                        uni.fvTenant(self.env.tenant).\
                            fvAp(self.env.app).\
                                fvESg(obj.metadata.name).POST()
                        
                        uni.fvTenant(self.env.tenant).\
                            fvAp(self.env.app).\
                                fvESg(obj.metadata.name).\
                                    fvRsScope(tnFvCtxName=self.env.vrf).POST()
                        
                        uni.fvTenant(self.env.tenant).\
                            fvAp(self.env.app).\
                                fvESg(obj.metadata.name).\
                                    fvRsSecInherited(tDn=self.env.contract_master).POST()
                        
                        uni.fvTenant(self.env.tenant).\
                            fvAp(self.env.app).\
                                fvESg(obj.metadata.name).\
                                    fvTagSelector(matchKey="namespace",\
                                                  matchValue=obj.metadata.name).POST()
                        
                        #This is not idea as PODs are tagged "twice" when I start the controller up the first time.
                        pods = await v1.list_namespaced_pod(obj.metadata.name, field_selector='status.phase=Running')
                        for pod in pods.items:
                           self.set_tag_pod(pod,obj.metadata.name)

                    # If a NS becomes ESG Disabled, delete the ESG in ACI and then remove the tag from all the existing PODs
                    elif obj.metadata.name in self.esg_enabled_ns:
                        logger.info("Namespace %s is No More ESG Enabled", obj.metadata.name)
                        self.esg_enabled_ns.remove(obj.metadata.name)
                        uni  = self.randApic().mit.polUni()
                        pods = await v1.list_namespaced_pod(obj.metadata.name)
                        for pod in pods.items:
                            self.clear_tag_pod(pod,obj.metadata.name)
                        uni.fvTenant(self.env.tenant).fvAp(self.env.app).fvESg(obj.metadata.name).DELETE()

    async def watch_pods(self):
        async with client.ApiClient() as api:
            v1 = client.CoreV1Api(api)
            async with watch.Watch().stream(v1.list_pod_for_all_namespaces, field_selector='status.phase=Running') as stream:
                async for event in stream:
                    evt, pod = event["type"], event["object"]
                    if pod.metadata.namespace in self.esg_enabled_ns:
                        if evt == "ADDED":
                            logger.info("New POD %s Detected in the ESG enabled ns %s", pod.metadata.name, pod.metadata.namespace)
                            self.set_tag_pod(pod,pod.metadata.namespace)
                        elif evt == "DELETED":
                            logger.info("POD %s Deleted in the ESG enabled ns %s", pod.metadata.name, pod.metadata.namespace)
                            self.clear_tag_pod(pod,pod.metadata.namespace)
                    self.booting= False

    async def watch_services(self):
        async with client.ApiClient() as api:
            v1 = client.CoreV1Api(api)
            async with watch.Watch().stream(v1.list_service_for_all_namespaces) as stream:
                async for event in stream:
                    evt, svc = event["type"], event["object"]
                    if svc.spec.type == "LoadBalancer" and svc.metadata.labels.get("extEpg-enabled") == "true":
                        self.extEPG_svc.append(svc.metadata.namespace + '-' + svc.metadata.name)
                        logger.info("Service %s Detected with ip %s adding to the L3OUT", svc.metadata.name, svc.status.load_balancer.ingress[0].ip)
                        self.create_extEPG(svc)
                    elif svc.metadata.namespace + '-' + svc.metadata.name in self.extEPG_svc:
                        logger.info("Service %s Deleted from L3OUT", svc.metadata.name)
                        self.delete_extEPG(svc)

    def run(self):
        loop = asyncio.get_event_loop()

        # Load the kubeconfig file specified in the KUBECONFIG environment
        # variable, or fall back to `~/.kube/config`.
        if self.is_local_mode(): 
            loop.run_until_complete(config.load_kube_config(config_file = self.env.kube_config))
        elif self.is_cluster_mode():
            loop.run_until_complete(config.load_kube_config())
        else:
            logger.error("Invalid Mode, %s. Only LOCAL or CLUSTER is supported.", self.env.mode)
            exit()

        # Define the tasks to watch namespaces and pods. The order here is important:
        # The tasks are in a loop so I don't need to add tags to PODs in the watch_namespaces method 
        # Since the first time we start the controller, we first load the namespaces and then the pods.

        tasks = [
            asyncio.ensure_future(self.watch_namespaces()),
            asyncio.ensure_future(self.watch_pods()),
            asyncio.ensure_future(self.watch_services()),
        ]
        # Push tasks into event loop.
        loop.run_until_complete(asyncio.wait(tasks))
        loop.close()


env = ACCEnvVariables()
loop = asyncio.get_event_loop()
cont = ACController(env)
cont.run()

