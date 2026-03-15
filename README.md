# FluxCD

## Description
- This repository utilizes FluxCD to control the state of my homelab clusters

## Cluster Details

### Development
- Kubernetes: rke2
- Nodes: 6
    - server: 3
    - agent: 3
- os: ubuntu24
- arch: amd64

### Production
- Kubernetes: rke2
- Nodes: 3
    - Server: 1
    - Agent: 2
- OS: ubuntu24
- Arch: amd64

### Bootstrapping
- deployed via [FluxCD Operator](https://fluxoperator.dev/docs/guides/install/)