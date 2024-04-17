# aci-cilium-controller

This is a proof of concept code to:
- dynamically push ESGs and Policy TAGs into ACI
- dynamically create extEPGs for services advertised over BGP.

For example, to run aci-cilium-controller outside of a K8s cluster do the following:

```bash
export MODE=LOCAL APIC_IPS="10.67.185.102,10.67.185.42,10.67.185.41" CERT_NAME=automation.crt CERT_USER=automation TENANT=openshift-cilium-c1 APP=ACC-Controlled VRF=k8s VRF_TENANT=common KEY_PATH=/home/cisco/Coding/pki/automation.key KUBE_CONFIG=/home/cisco/Coding/aci-cilium-controller/credentials/ocp-cilium-kubeconfig CONTRACT_MASTER=uni/tn-openshift-cilium-c1/ap-Cluster/esg-contract-master L3OUT_NAME=services
```

At the moment this is a proof of concept and I don't do any reconciliation with APIC: i.e. if you delete objects in APIC the controller dosen't know. 