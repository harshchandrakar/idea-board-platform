{{- define "idea.labels" -}}
app.kubernetes.io/name: idea-board
app.kubernetes.io/managed-by: {{ .Release.Service }}
env: {{ .Release.Namespace }}
{{- end -}}
