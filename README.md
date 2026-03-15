# FluxCD

## Description
- This repository utilizes FluxCD to control homelab cluster state

## Cluster Details

### Staging
- Kubernetes: rke2
- Nodes: 4
    - server: 1
    - agent: 3
- OS: ubuntu24
- Arch: amd64

### Production
- Kubernetes: rke2
- Nodes: 6
    - Server: 3
    - Agent: 3
- OS: ubuntu24
- Arch: amd64

### Bootstrapping
- deployed via [FluxCD Operator](https://fluxoperator.dev/docs/guides/install/)
