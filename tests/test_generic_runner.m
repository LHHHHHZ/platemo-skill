function test_generic_runner(platemoRoot,outputRoot)
% 独立复制通用运行器，不复制任何算法适配器实现。
    assert(isfolder(outputRoot),'Create a fresh output directory first.');
    source = fileparts(which('run_platemo_batch'));
    isolated = fullfile(outputRoot,'core_only');
    mkdir(isolated); mkdir(fullfile(isolated,'adapters'));
    copyfile(fullfile(source,'run_platemo_batch.m'),isolated);
    copyfile(fullfile(source,'resolve_runtime_adapter.m'),isolated);
    copyfile(fullfile(source,'adapters','registry.json'),fullfile(isolated,'adapters'));
    previousPath = path;
    cleanup = onCleanup(@()path(previousPath)); %#ok<NASGU>
    addpath(isolated,'-begin');
    clear run_platemo_batch resolve_runtime_adapter;
    cd(platemoRoot);
    cfg = struct('algorithms',{{struct('class','NSGAII'),struct('class','NSGAIII')}}, ...
        'problems',{{struct('class','DTLZ2','M',3,'D',8)}},'N',12,'maxFE',24,'runs',2, ...
        'metrics',{{'IGD','HV'}},'save_count',2,'experiment_root',outputRoot,'experiment_id','generic');
    configPath = fullfile(outputRoot,'generic_config.json');
    writeConfig(configPath,cfg);
    run_platemo_batch(configPath);
    manifest = jsondecode(fileread(fullfile(outputRoot,'generic','manifest.json')));
    assert(strcmp(manifest.status,'completed') && numel(manifest.records)==4);
    assert(manifest.config.seed_policy.schema_version==2);
    for i=1:numel(manifest.records)
        record=manifest.records(i);
        if iscell(manifest.records), record=manifest.records{i}; end
        assert(strcmp(record.runtime_adapter.id,'none'));
        assert(~isfield(record,'runtime_diagnostics') && ~isfield(record.randomness,'python'));
    end
    cfg.experiment_id='missing_adapter';
    cfg.algorithms={struct('class','NSGAII','adapter','missing')};
    writeConfig(configPath,cfg);
    expectReject(configPath,outputRoot,cfg.experiment_id,'unavailable');
    cfg.experiment_id='missing_capability';
    cfg.algorithms={struct('class','NSGAII','required_capabilities',{{'runtime_mechanism'}})};
    writeConfig(configPath,cfg);
    expectReject(configPath,outputRoot,cfg.experiment_id,'Required capabilities');
    fprintf('GENERIC_RUNNER_TEST_PASS no_adapter_implementations=1 ordinary_runs=4 missing_adapter_rejected=1 missing_capability_rejected=1\n');
end

function expectReject(configPath,root,id,message)
    rejected=false;
    try, run_platemo_batch(configPath); catch ME, rejected=contains(ME.message,message); end
    assert(rejected && ~isfolder(fullfile(root,id)),'Required extension must fail before simulation.');
end

function writeConfig(path,cfg)
    fid=fopen(path,'w','n','UTF-8');
    assert(fid>=0,'Cannot create test config.');
    cleanup=onCleanup(@()fclose(fid)); %#ok<NASGU>
    fprintf(fid,'%s',jsonencode(cfg));
end
