# Deploy runbook

## How deploys work
All deploys go through Git. Merge to main, CI builds an image, CI bumps the image tag in gitops/manifests, and ArgoCD syncs the cluster. Never run kubectl apply by hand on shared clusters.

## How to roll back
Revert the commit that bumped the image tag and push to main. ArgoCD will sync the previous version within a few minutes. For an emergency, use the ArgoCD UI and click History and Rollback on the application, then fix Git afterwards.

## Deploy windows
Avoid deploying after 17:00 on Fridays. The deploy risk model scores late and large changes higher.
