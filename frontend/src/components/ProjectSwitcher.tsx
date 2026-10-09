import { useEffect, useMemo, useState } from 'react'
import { EditOutlined, PlusOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Button, Flex, Select, Tooltip, Typography } from 'antd'

import { listProjects, type Project } from '../api/projects'
import { ProjectDialog } from '../features/projects/ProjectDialog'
import { DeleteProjectButton } from '../features/projects/DeleteProjectButton'
import { useAppStore } from '../stores/useAppStore'

export function ProjectSwitcher() {
  const currentProjectId = useAppStore((state) => state.currentProjectId)
  const setCurrentProjectId = useAppStore((state) => state.setCurrentProjectId)
  const [dialogMode, setDialogMode] = useState<'create' | 'edit' | null>(null)

  const projectsQuery = useQuery({
    queryKey: ['projects'],
    queryFn: listProjects,
  })

  const projects = projectsQuery.data ?? []
  const currentProject = useMemo(
    () => projects.find((project) => project.id === currentProjectId) ?? null,
    [currentProjectId, projects],
  )

  useEffect(() => {
    if (!projectsQuery.isSuccess) return
    if (projects.length === 0) {
      if (currentProjectId !== null) setCurrentProjectId(null)
      return
    }
    if (!projects.some((project) => project.id === currentProjectId)) {
      setCurrentProjectId(projects[0].id)
    }
  }, [currentProjectId, projects, projectsQuery.isSuccess, setCurrentProjectId])

  function handleSaved(project: Project) {
    setCurrentProjectId(project.id)
  }

  if (projectsQuery.isPending) {
    return <Typography.Text type="secondary">正在读取项目…</Typography.Text>
  }

  if (projectsQuery.isError) {
    return <Typography.Text type="danger">项目列表读取失败</Typography.Text>
  }

  if (projects.length === 0) {
    return (
      <>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setDialogMode('create')}>
          新建项目
        </Button>
        <ProjectDialog
          open={dialogMode === 'create'}
          onClose={() => setDialogMode(null)}
          onSaved={handleSaved}
        />
      </>
    )
  }

  return (
    <>
      <Flex align="center" gap={8}>
        <Typography.Text type="secondary">当前项目</Typography.Text>
        <Select
          aria-label="当前项目"
          value={currentProject?.id}
          style={{ minWidth: 220 }}
          options={projects.map((project) => ({ label: project.name, value: project.id }))}
          onChange={setCurrentProjectId}
        />
        {currentProject ? <DeleteProjectButton project={currentProject} /> : null}
        <Tooltip title="编辑当前项目">
          <Button
            aria-label="编辑当前项目"
            icon={<EditOutlined />}
            disabled={!currentProject}
            onClick={() => setDialogMode('edit')}
          />
        </Tooltip>
        <Tooltip title="新建项目">
          <Button
            aria-label="新建项目"
            icon={<PlusOutlined />}
            onClick={() => setDialogMode('create')}
          />
        </Tooltip>
      </Flex>

      <ProjectDialog
        open={dialogMode === 'create'}
        onClose={() => setDialogMode(null)}
        onSaved={handleSaved}
      />
      <ProjectDialog
        open={dialogMode === 'edit'}
        project={currentProject}
        onClose={() => setDialogMode(null)}
        onSaved={handleSaved}
      />
    </>
  )
}
