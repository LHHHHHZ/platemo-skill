function test_iteration_runner(platemo_root,output_root,stage)
%TEST_ITERATION_RUNNER 两阶段验证方案快照；中间用 Python prepare 生成方案。
    assert(isfolder(output_root),'Create the test output directory first.');
    cd(platemo_root);
    cfg = struct('algorithms',{{struct('class','NSGAII','params',[])}}, ...
        'problems',{{struct('class','DTLZ2','M',3,'D',8)}}, ...
        'N',12,'maxFE',24,'runs',3,'seeds',{{11,22,33}}, ...
        'metrics',{{'IGD','HV'}},'save_count',2,'experiment_root',output_root);
    cfg.experiment_id = ['iteration_',stage];
    configPath = fullfile(output_root,[stage,'_config.json']);
    if strcmp(stage,'candidate'), cfg.iteration_plan = 'plan.json'; end
    writeConfig(configPath,cfg);
    run_platemo_batch(configPath);
    if strcmp(stage,'candidate')
        folder = fullfile(output_root,cfg.experiment_id);
        manifest = jsondecode(fileread(fullfile(folder,'manifest.json')));
        assert(strcmp(fileread(fullfile(folder,'iteration_plan.json')),fileread(fullfile(output_root,'plan.json'))));
        assert(numel(manifest.config.iteration_plan.sha256) == 64);
        cfg = manifest.config;
        cfg.experiment_id = 'changed_plan_must_fail';
        cfg.iteration_plan.sha256 = 'changed';
        writeConfig(configPath,cfg);
        rejected = false;
        try
            run_platemo_batch(configPath);
        catch ME
            rejected = contains(ME.message,'Iteration plan changed');
        end
        assert(rejected,'A changed locked plan must be rejected.');
        assert(~isfolder(fullfile(output_root,cfg.experiment_id)));
    end
    fprintf('ITERATION_RUNNER_TEST_PASS stage=%s\n',stage);
end

function writeConfig(path,cfg)
    fid = fopen(path,'w','n','UTF-8');
    assert(fid >= 0,'Cannot create test config.');
    guard = onCleanup(@()fclose(fid)); %#ok<NASGU>
    fprintf(fid,'%s',jsonencode(cfg));
end
