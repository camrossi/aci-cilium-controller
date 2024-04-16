# aci-cilium-controller

This is a proof of concept code to dynamically push ESGs and Policy TAGs into ACI.

For example, to run aci-cilium-controller outside of a K8s cluster do the following:

```bash
export MODE=LOCAL APIC_IPS="IP1,IP2" CERT_NAME=automation.crt CERT_USER=automation TENANT=openshift-cilium-c1 APP=ACC-Controlled VRF=k8s VRF_TENANT=common KEY_PATH=/home/cisco/Coding/pki/automation.key KUBE_CONFIG=/home/cisco/Coding/aci-cilium-controller/credentials/ocp-cilium-kubeconfig CONTRACT_MASTER=uni/tn-openshift-cilium-c1/ap-Cluster/esg-contract-master
```