function adapter = resolve_runtime_adapter(spec,scriptDir)
%RESOLVE_RUNTIME_ADAPTER 仅加载匹配的本地扩展，所需能力缺失时明确失败。
    registry = jsondecode(fileread(fullfile(scriptDir,'adapters','registry.json')));
    assert(registry.schema_version == 1,'Unsupported adapter registry.');
    entries = registry.adapters;
    if ~iscell(entries), entries = num2cell(entries); end
    adapter = struct('id','none','version',1,'capabilities',{{}},'sources',{{}});
    matched = false;
    for i = 1:numel(entries)
        entry = entries{i};
        if any(strcmp(char(spec.class),cellstr(entry.algorithms)))
            assert(~matched,'Ambiguous algorithm adapter registration.');
            adapter = entry;
            adapter.capabilities = cellstr(entry.capabilities);
            adapter.sources = cellstr(entry.sources);
            matched = true;
        end
    end
    requested = 'auto';
    if isfield(spec,'adapter'), requested = char(spec.adapter); end
    assert(strcmp(requested,'auto') || strcmp(requested,adapter.id), ...
        'Adapter %s is unavailable or incompatible with %s.',requested,char(spec.class));
    if isfield(spec,'required_capabilities')
        required = cellstr(spec.required_capabilities);
        assert(all(ismember(required,[{'matlab_random'},adapter.capabilities(:)'])), ...
            'Required capabilities are not provided by the selected adapter.');
    end
    for i = 1:numel(adapter.sources)
        path = char(java.io.File(fullfile(scriptDir,adapter.sources{i})).getCanonicalPath());
        root = [char(java.io.File(scriptDir).getCanonicalPath()),filesep];
        assert(startsWith(path,root) && isfile(path),'Required adapter source is unavailable: %s',path);
    end
    if matched
        classFile = fullfile(scriptDir,adapter.sources{1});
        addpath(fileparts(classFile));
        assert(strcmpi(which(adapter.matlab_class),classFile),'Adapter class resolved to an unexpected location.');
    end
end
