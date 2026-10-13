pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        skipDefaultCheckout(true)
        timestamps()
        timeout(time: 60, unit: 'MINUTES')
    }

    parameters {
        string(
            name: 'IMAGE_NAMESPACE',
            defaultValue: 'YOUR_GITHUB_USER',
            trim: true,
            description: 'GitHub username or organization that owns the GHCR images'
        )
    }

    environment {
        REGISTRY = 'ghcr.io'
        SKIP_CI = 'false'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                script {
                    env.GIT_COMMIT = sh(
                        returnStdout: true,
                        script: 'git rev-parse HEAD'
                    ).trim()
                }
            }
        }

        stage('Detect generated deployment commit') {
            steps {
                script {
                    def subject = sh(
                        returnStdout: true,
                        script: 'git log -1 --pretty=%s'
                    ).trim()
                    env.SKIP_CI = subject.contains('[skip ci]') ? 'true' : 'false'
                }
            }
        }

        stage('Validate image namespace') {
            when {
                allOf {
                    branch 'main'
                    expression { env.SKIP_CI != 'true' }
                }
            }
            steps {
                script {
                    def namespace = params.IMAGE_NAMESPACE.trim()
                    if (namespace.equalsIgnoreCase('YOUR_GITHUB_USER') ||
                        !(namespace ==~ /[A-Za-z0-9][A-Za-z0-9-]{0,38}/)) {
                        error('Set IMAGE_NAMESPACE to the lowercase-compatible GitHub user or organization that owns the GHCR packages.')
                    }
                    env.IMAGE_NAMESPACE = namespace.toLowerCase()
                    env.IMAGE_TAG = env.GIT_COMMIT
                }
            }
        }

        stage('Test') {
            when {
                expression { env.SKIP_CI != 'true' }
            }
            steps {
                sh 'python3 -m venv .venv'
                sh '.venv/bin/python -m pip install -r requirements-dev.txt'
                sh 'npm ci --prefix services/portal/web'
                sh 'npm run build --prefix services/portal/web'
                sh '.venv/bin/python -m pytest -q tests'
            }
        }

        stage('Build, scan, and push images') {
            when {
                allOf {
                    branch 'main'
                    expression { env.SKIP_CI != 'true' }
                }
            }
            steps {
                withCredentials([usernamePassword(
                    credentialsId: 'ghcr-credentials',
                    usernameVariable: 'GHCR_USER',
                    passwordVariable: 'GHCR_TOKEN'
                )]) {
                    script {
                        try {
                            sh 'printf "%s" "$GHCR_TOKEN" | docker login "$REGISTRY" --username "$GHCR_USER" --password-stdin'
                            def services = ['llm-gateway', 'model-serving', 'docs-assistant', 'aiops-agent', 'portal']
                            services.each { service ->
                                def image = "${env.REGISTRY}/${env.IMAGE_NAMESPACE}/idp-${service}:${env.IMAGE_TAG}"
                                sh "docker build -f services/${service}/Dockerfile -t ${image} ."
                                sh "docker push ${image}"
                                sh "trivy image --severity CRITICAL --exit-code 0 ${image}"
                            }
                        } finally {
                            sh(script: 'docker logout "$REGISTRY"', returnStatus: true)
                        }
                    }
                }
            }
        }

        stage('Update GitOps image references') {
            when {
                allOf {
                    branch 'main'
                    expression { env.SKIP_CI != 'true' }
                }
            }
            steps {
                withCredentials([gitUsernamePassword(
                    credentialsId: 'github-push-credentials',
                    gitToolName: 'Default'
                )]) {
                    sh '''
                        set -eu
                        for service in llm-gateway model-serving docs-assistant aiops-agent portal; do
                            kustomization="gitops/manifests/$service/kustomization.yaml"
                            deployment="gitops/manifests/$service/deployment.yaml"
                            sed -i "s#ghcr.io/YOUR_GITHUB_USER#ghcr.io/$IMAGE_NAMESPACE#g; s#newTag: .*#newTag: $IMAGE_TAG#" "$kustomization"
                            sed -i "s#ghcr.io/YOUR_GITHUB_USER#ghcr.io/$IMAGE_NAMESPACE#g" "$deployment"
                        done

                        git add gitops/manifests
                        if git diff --cached --quiet; then
                            echo "GitOps manifests already reference this image tag."
                        else
                            git config user.name "Jenkins"
                            git config user.email "jenkins@users.noreply.github.com"
                            short_sha="$(printf '%.7s' "$GIT_COMMIT")"
                            git commit -m "deploy: $short_sha [skip ci]"
                            git push origin HEAD:main
                        fi
                    '''
                }
            }
        }
    }
}
