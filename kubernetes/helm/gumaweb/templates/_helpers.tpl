{{- define "gumaweb.fullname" -}}
{{- printf "%s" .Release.Name | trunc 40 | trimSuffix "-" -}}
{{- end -}}

{{- define "gumaweb.labels" -}}
app.kubernetes.io/part-of: gumaweb
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "gumaweb.selector" -}}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "gumaweb.image" -}}
{{- $tag := .root.Values.image.tag | default .root.Chart.AppVersion -}}
{{- printf "%s/%s:%s" .root.Values.image.registry .name $tag -}}
{{- end -}}

{{- define "gumaweb.secretName" -}}
{{- .Values.secrets.existingSecret | default (printf "%s-secrets" (include "gumaweb.fullname" .)) -}}
{{- end -}}

{{/* Restricted pod security context shared by every app container */}}
{{- define "gumaweb.podSecurity" -}}
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
  fsGroup: 10001
  seccompProfile: { type: RuntimeDefault }
{{- end -}}

{{- define "gumaweb.containerSecurity" -}}
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities: { drop: ["ALL"] }
{{- end -}}

{{/* Environment shared by the API, migration job and CronJobs */}}
{{- define "gumaweb.apiEnv" -}}
envFrom:
  - configMapRef:
      name: {{ include "gumaweb.fullname" . }}-config
env:
  - name: JWT_SECRET_KEY
    valueFrom: { secretKeyRef: { name: {{ include "gumaweb.secretName" . }}, key: JWT_SECRET_KEY } }
  - name: DATABASE_URL
    valueFrom: { secretKeyRef: { name: {{ include "gumaweb.secretName" . }}, key: DATABASE_URL } }
  - name: S3_ACCESS_KEY
    valueFrom: { secretKeyRef: { name: {{ include "gumaweb.secretName" . }}, key: S3_ACCESS_KEY, optional: true } }
  - name: S3_SECRET_KEY
    valueFrom: { secretKeyRef: { name: {{ include "gumaweb.secretName" . }}, key: S3_SECRET_KEY, optional: true } }
  - name: SMTP_USER
    valueFrom: { secretKeyRef: { name: {{ include "gumaweb.secretName" . }}, key: SMTP_USER, optional: true } }
  - name: SMTP_PASSWORD
    valueFrom: { secretKeyRef: { name: {{ include "gumaweb.secretName" . }}, key: SMTP_PASSWORD, optional: true } }
  - name: FIRST_ADMIN_EMAIL
    valueFrom: { secretKeyRef: { name: {{ include "gumaweb.secretName" . }}, key: FIRST_ADMIN_EMAIL, optional: true } }
  - name: FIRST_ADMIN_PASSWORD
    valueFrom: { secretKeyRef: { name: {{ include "gumaweb.secretName" . }}, key: FIRST_ADMIN_PASSWORD, optional: true } }
{{- end -}}

{{/* Writable volume for published sites: shared RWX PVC (local mode) or scratch space (s3 mode). */}}
{{- define "gumaweb.sitesVolume" -}}
- name: sites
{{- if eq .Values.config.storageBackend "s3" }}
  emptyDir: {}
{{- else }}
  persistentVolumeClaim: { claimName: {{ include "gumaweb.fullname" . }}-sites }
{{- end }}
{{- end -}}
