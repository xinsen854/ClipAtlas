class AutoDirectorError(RuntimeError):
    pass


class AutoDirectorUnavailableError(AutoDirectorError):
    pass


class StorySkillError(AutoDirectorError):
    pass


class StoryEvidenceUnavailableError(AutoDirectorError):
    pass


class StoryOutlineNotFoundError(AutoDirectorError):
    pass


class StoryOutlineConflictError(AutoDirectorError):
    pass
