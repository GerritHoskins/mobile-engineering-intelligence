output "task_definition_family" {
  value = aws_ecs_task_definition.this.family
}

output "schedule_group_name" {
  value = aws_scheduler_schedule_group.this.name
}

output "schedule_name" {
  value = aws_scheduler_schedule.ingest.name
}
