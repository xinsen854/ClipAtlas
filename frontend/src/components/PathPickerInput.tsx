import { useMutation } from '@tanstack/react-query'
import { Button, Flex, Input } from 'antd'

import { pickDirectory, pickFile } from '../api/system'

type PathPickerInputProps = {
  value?: string
  onChange?: (value: string) => void
  placeholder?: string
  picker?: 'directory' | 'file'
  disabled?: boolean
  'aria-label'?: string
}

export function PathPickerInput({
  value,
  onChange,
  placeholder,
  picker = 'directory',
  disabled,
  'aria-label': ariaLabel,
}: PathPickerInputProps) {
  const mutation = useMutation({
    mutationFn: picker === 'directory' ? pickDirectory : pickFile,
    onSuccess: (path) => {
      if (path) onChange?.(path)
    },
  })

  return (
    <Flex gap={8}>
      <Input
        value={value}
        onChange={(event) => onChange?.(event.target.value)}
        placeholder={placeholder}
        disabled={disabled || mutation.isPending}
        aria-label={ariaLabel}
      />
      <Button
        onClick={() => mutation.mutate()}
        loading={mutation.isPending}
        disabled={disabled}
        aria-label={`选择${picker === 'directory' ? '文件夹' : '文件'}`}
      >
        选择
      </Button>
    </Flex>
  )
}
