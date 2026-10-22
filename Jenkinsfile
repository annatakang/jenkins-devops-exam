pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        timestamps()
        timeout(time: 120, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '15'))
    }

    triggers {
        pollSCM('H/5 * * * *')
    }

    stages {
        stage('Validate') {
            steps {
                script {
                    env.IMAGE_TAG = sh(
                        script: 'git rev-parse --short=12 HEAD',
                        returnStdout: true
                    ).trim() + "-${env.BUILD_NUMBER}"
                }
                sh '''
                    set -eu
                    git remote -v
                    docker info --format '{{.ServerVersion}}'
                    docker compose config --quiet
                    helm lint charts
                    helm template jenkins-exam charts --namespace dev > /dev/null
                    python3 -c 'import ast; from pathlib import Path; [ast.parse(p.read_text()) for p in Path("scripts").glob("*.py")]'
                '''
            }
        }

        stage('Build and test with Compose') {
            options {
                timeout(time: 30, unit: 'MINUTES')
            }
            steps {
                sh 'python3 scripts/compose_test.py'
            }
        }

        stage('Publish images') {
            when {
                branch 'master'
            }
            steps {
                withCredentials([usernamePassword(
                    credentialsId: 'dockerhub-credentials',
                    usernameVariable: 'DOCKERHUB_USER',
                    passwordVariable: 'DOCKERHUB_TOKEN'
                )]) {
                    sh '''
                        set -eu
                        set +x
                        export DOCKER_CONFIG="$(mktemp -d)"
                        trap 'rm -rf "$DOCKER_CONFIG"' EXIT
                        printf '%s' "$DOCKERHUB_TOKEN" |
                          docker login --username "$DOCKERHUB_USER" --password-stdin
                        docker push "annatakang77/jenkins-exam-movie:$IMAGE_TAG"
                        docker push "annatakang77/jenkins-exam-cast:$IMAGE_TAG"
                    '''
                }
            }
        }

        stage('Deploy dev') {
            when {
                branch 'master'
            }
            steps {
                sh 'python3 scripts/deploy.py dev "$IMAGE_TAG"'
            }
        }

        stage('Deploy QA') {
            when {
                branch 'master'
            }
            steps {
                sh 'python3 scripts/deploy.py qa "$IMAGE_TAG"'
            }
        }

        stage('Deploy staging') {
            when {
                branch 'master'
            }
            steps {
                sh 'python3 scripts/deploy.py staging "$IMAGE_TAG"'
            }
        }

        stage('Approve and deploy production') {
            when {
                beforeInput true
                branch 'master'
            }
            options {
                timeout(time: 30, unit: 'MINUTES')
            }
            input {
                message 'Deploy the tested image version to production?'
                ok 'Deploy production'
            }
            steps {
                sh 'python3 scripts/deploy.py prod "$IMAGE_TAG"'
            }
        }
    }

    post {
        success {
            echo "Pipeline succeeded. Tested image tag: ${env.IMAGE_TAG}"
        }
        failure {
            echo 'Pipeline failed. Review the first failing stage in Console Output.'
        }
    }
}
