import * as React from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm, useWatch } from 'react-hook-form'

import { getFieldErrors, isApiError, ROOT_ERROR_KEY } from '@/api/errors'
import {
  AuthMode,
  ModelType,
  type CreateModelRequest,
  type ModelDto,
  type UpdateModelRequest,
} from '@/api/types'
import { FormRootError } from '@/components/form/FormRootError'
import { SecretInput } from '@/components/form/SecretInput'
import { SubmitButton } from '@/components/form/SubmitButton'
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/form/form'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { modelEditSchema, REASONING_EFFORTS } from '@/schemas/model.schema'

/** Create and edit share one form; the API generates the model's id. */
type FormValues = {
  displayName: string
  name: string
  provider: string
  connectionString?: string
  authMode: AuthMode
  type: ModelType[]
  apiKey?: string
  embeddingDimension?: number
  reasoningEffort?: string
}

interface ModelFormProps {
  mode: 'create' | 'edit'
  model?: ModelDto
  submitLabel: string
  pending: boolean
  onSubmit: (body: CreateModelRequest | UpdateModelRequest) => Promise<unknown>
  onCancel?: () => void
}

const TYPE_LABELS: Record<ModelType, string> = {
  [ModelType.Embedding]: 'Embedding',
  [ModelType.Vision]: 'Vision',
  [ModelType.Thinking]: 'Thinking',
}

export function ModelForm({
  mode,
  model,
  submitLabel,
  pending,
  onSubmit,
  onCancel,
}: ModelFormProps) {
  const [rootError, setRootError] = React.useState<string | null>(null)

  const form = useForm<FormValues>({
    resolver: zodResolver(modelEditSchema) as never,
    defaultValues: {
      displayName: model?.displayName ?? '',
      name: model?.name ?? '',
      provider: model?.provider ?? '',
      connectionString: model?.connectionString ?? '',
      authMode: model?.authMode ?? AuthMode.ApiKey,
      type: model?.type ?? [],
      apiKey: '',
      embeddingDimension: model?.embeddingDimension ?? undefined,
      reasoningEffort: model?.reasoningEffort ?? undefined,
    },
  })

  // `useWatch` rather than `form.watch()`: the latter returns a fresh function
  // the React Compiler cannot memoize, so it skips optimizing this component.
  const authMode = useWatch({ control: form.control, name: 'authMode' })
  const types = useWatch({ control: form.control, name: 'type' })
  const isEmbedding = types.includes(ModelType.Embedding)
  const needsApiKey = authMode === AuthMode.ApiKey

  const submit = async (values: FormValues) => {
    setRootError(null)

    const payload: CreateModelRequest = {
      displayName: values.displayName,
      name: values.name,
      provider: values.provider,
      connectionString: values.connectionString?.trim() ? values.connectionString : null,
      authMode: values.authMode,
      type: values.type,
      apiKey: needsApiKey ? (values.apiKey ?? null) : null,
      embeddingDimension: isEmbedding ? (values.embeddingDimension ?? null) : null,
      reasoningEffort:
        !isEmbedding && values.reasoningEffort?.trim() ? values.reasoningEffort : null,
    }

    try {
      await onSubmit(payload)
    } catch (error) {
      if (!isApiError(error)) {
        setRootError('Could not save the model configuration.')
        return
      }

      if (error.status === 409) {
        setRootError(error.detail ?? error.title)
        return
      }

      const fields = getFieldErrors(error)
      let attached = false
      for (const key of [
        'displayName',
        'name',
        'provider',
        'connectionString',
        'authMode',
        'apiKey',
        'embeddingDimension',
        'reasoningEffort',
      ] as const) {
        const message = fields[key]?.[0]
        if (message) {
          form.setError(key, { message })
          attached = true
        }
      }
      if (!attached) {
        setRootError(
          fields[ROOT_ERROR_KEY]?.[0] ?? error.detail ?? error.title,
        )
      }
    }
  }

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(submit)} className="space-y-6" noValidate>
        <FormRootError message={rootError ?? undefined} />

        <div className="grid gap-6 sm:grid-cols-2">
          <FormField
            control={form.control}
            name="displayName"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Display name</FormLabel>
                <FormControl>
                  <Input {...field} placeholder="Chat GPT-4o" autoFocus={mode === 'edit'} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="provider"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Provider</FormLabel>
                <FormControl>
                  <Input {...field} placeholder="openai" spellCheck={false} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>

        <FormField
          control={form.control}
          name="name"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Model name</FormLabel>
              <FormControl>
                <Input {...field} placeholder="gpt-4o" spellCheck={false} />
              </FormControl>
              <FormDescription>Exactly as the provider names it.</FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name="connectionString"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Endpoint</FormLabel>
              <FormControl>
                <Input
                  {...field}
                  placeholder="https://api.openai.com/v1"
                  spellCheck={false}
                />
              </FormControl>
              <FormDescription>
                Leave blank to use the provider&rsquo;s default endpoint.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name="type"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Capabilities</FormLabel>
              <div className="flex flex-wrap gap-4">
                {Object.values(ModelType).map((capability) => {
                  const checked = field.value.includes(capability)
                  return (
                    <div key={capability} className="flex items-center gap-2">
                      <Checkbox
                        id={`type-${capability}`}
                        checked={checked}
                        onCheckedChange={(next) =>
                          field.onChange(
                            next
                              ? [...field.value, capability]
                              : field.value.filter((entry) => entry !== capability),
                          )
                        }
                      />
                      <Label htmlFor={`type-${capability}`} className="font-normal">
                        {TYPE_LABELS[capability]}
                      </Label>
                    </div>
                  )
                })}
              </div>
              <FormDescription>May be left empty.</FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        {isEmbedding ? (
          <FormField
            control={form.control}
            name="embeddingDimension"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Embedding dimension</FormLabel>
                <FormControl>
                  <Input
                    type="number"
                    min={1}
                    value={field.value ?? ''}
                    name={field.name}
                    ref={field.ref}
                    onBlur={field.onBlur}
                    onChange={(event) =>
                      field.onChange(
                        event.target.value === '' ? undefined : event.target.valueAsNumber,
                      )
                    }
                    placeholder="1536"
                  />
                </FormControl>
                <FormDescription>
                  Required for an embedding model, and must match what the provider
                  returns.
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
        ) : (
          <FormField
            control={form.control}
            name="reasoningEffort"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Reasoning effort</FormLabel>
                <Select
                  value={field.value ?? 'none'}
                  onValueChange={(value) =>
                    field.onChange(value === 'none' ? undefined : value)
                  }
                >
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue placeholder="Provider default" />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectItem value="none">Provider default</SelectItem>
                    {REASONING_EFFORTS.map((effort) => (
                      <SelectItem key={effort} value={effort}>
                        {effort}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FormDescription>
                  Only meaningful for a chat model; not allowed on an embedding model.
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
        )}

        <FormField
          control={form.control}
          name="authMode"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Authentication</FormLabel>
              <Select value={field.value} onValueChange={field.onChange}>
                <FormControl>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  <SelectItem value={AuthMode.ApiKey}>API key</SelectItem>
                  <SelectItem value={AuthMode.ManagedIdentity}>Managed identity</SelectItem>
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />

        {needsApiKey ? (
          <div className="space-y-3">
            {mode === 'edit' ? (
              <Alert>
                <AlertTitle>Saving replaces the stored API key</AlertTitle>
                <AlertDescription>
                  The key is never sent back to the browser, and this endpoint replaces
                  the whole configuration. Re-enter the key to keep this model working,
                  or switch to managed identity to clear it deliberately.
                </AlertDescription>
              </Alert>
            ) : null}

            <FormField
              control={form.control}
              name="apiKey"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>API key</FormLabel>
                  <FormControl>
                    <SecretInput
                      {...field}
                      value={field.value ?? ''}
                      placeholder={
                        mode === 'edit' && model?.hasApiKey
                          ? 'Re-enter the API key'
                          : 'sk-…'
                      }
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <SubmitButton pending={pending} pendingLabel="Saving…">
            {submitLabel}
          </SubmitButton>
          {onCancel ? (
            <Button type="button" variant="outline" onClick={onCancel} disabled={pending}>
              Cancel
            </Button>
          ) : null}
        </div>
      </form>
    </Form>
  )
}
